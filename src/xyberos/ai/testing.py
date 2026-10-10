"""A deterministic AI provider for tests.

Nothing here touches a network or a vendor SDK. Replies play in order and the last one repeats, so
an "always rate limited" provider and a "fails once, then answers" provider are both one line. Every
scenario the facade must survive — delays, rate limits, transient faults, malformed payloads,
schema-invalid payloads, refusals, timeouts, and cancellation — is a scripted reply.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass

from xyberos.ai.contracts import (
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    FinishReason,
    Message,
    ModelCapabilities,
    ModelHealth,
    ModelStatus,
    ToolCall,
    Usage,
)
from xyberos.errors import (
    AIRateLimitError,
    AITimeoutError,
    AITransportError,
    AIUnsupportedCapabilityError,
)

DEFAULT_FAKE_MODEL = "fake-model"


@dataclass(frozen=True)
class ModelReply:
    """One scripted provider reply.

    ``delay`` is applied once per chat call and once per streamed chunk, which makes a slow provider
    easy to simulate without ever waiting in a test that times out first.
    """

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: Usage = Usage()
    finish_reason: FinishReason | None = FinishReason.STOP
    model: str = DEFAULT_FAKE_MODEL
    delay: float = 0.0
    error: BaseException | None = None
    chunks: tuple[str, ...] = ()

    @classmethod
    def ok(
        cls,
        content: str,
        *,
        usage: Usage | None = None,
        delay: float = 0.0,
        model: str = DEFAULT_FAKE_MODEL,
        chunks: Iterable[str] = (),
    ) -> ModelReply:
        """Return a successful reply, optionally scripted for streaming."""
        return cls(
            content=content,
            usage=usage or Usage(),
            delay=delay,
            model=model,
            chunks=tuple(chunks),
        )

    @classmethod
    def json_payload(
        cls,
        payload: object,
        *,
        usage: Usage | None = None,
        delay: float = 0.0,
        model: str = DEFAULT_FAKE_MODEL,
    ) -> ModelReply:
        """Return a reply whose content is the JSON encoding of ``payload``."""
        return cls.ok(json.dumps(payload), usage=usage, delay=delay, model=model)

    @classmethod
    def wrong_shape(
        cls, payload: object, *, usage: Usage | None = None, model: str = DEFAULT_FAKE_MODEL
    ) -> ModelReply:
        """Return valid JSON that does not satisfy a response schema."""
        return cls.ok(json.dumps(payload), usage=usage, model=model)

    @classmethod
    def malformed(
        cls, *, content: str = "this is not JSON", model: str = DEFAULT_FAKE_MODEL
    ) -> ModelReply:
        """Return content that cannot be parsed as JSON."""
        return cls.ok(content, model=model)

    @classmethod
    def refusal(
        cls, *, content: str = "I cannot help with that.", model: str = DEFAULT_FAKE_MODEL
    ) -> ModelReply:
        """Return a reply a provider has labelled a refusal."""
        return cls(content=content, finish_reason=FinishReason.REFUSAL, model=model)

    @classmethod
    def tools(
        cls,
        *tool_calls: ToolCall,
        content: str = "",
        usage: Usage | None = None,
        model: str = DEFAULT_FAKE_MODEL,
    ) -> ModelReply:
        """Return a reply that asks for tool calls."""
        return cls(
            content=content,
            tool_calls=tuple(tool_calls),
            usage=usage or Usage(),
            finish_reason=FinishReason.TOOL_CALLS,
            model=model,
        )

    @classmethod
    def failing(cls, error: BaseException, *, delay: float = 0.0) -> ModelReply:
        """Return a reply that raises ``error``."""
        return cls(error=error, delay=delay, finish_reason=None)

    @classmethod
    def rate_limited(cls, *, delay: float = 0.0) -> ModelReply:
        """Return a reply that raises :class:`~xyberos.errors.AIRateLimitError`."""
        return cls.failing(
            AIRateLimitError("the fake provider asked the client to slow down"), delay=delay
        )

    @classmethod
    def transient(cls, *, delay: float = 0.0) -> ModelReply:
        """Return a reply that raises a retryable transport failure."""
        return cls.failing(AITransportError("the fake provider failed transiently"), delay=delay)

    @classmethod
    def timeout(cls) -> ModelReply:
        """Return a reply that raises :class:`~xyberos.errors.AITimeoutError`."""
        return cls.failing(AITimeoutError("the fake provider timed out"))

    @classmethod
    def slow(cls, delay: float) -> ModelReply:
        """Return a successful reply that waits ``delay`` seconds of real time."""
        return cls(content=f"slow reply after {delay:g}s", delay=delay)


class FakeModelProvider:
    """A deterministic provider implementing the full provider contract.

    Capabilities default to permissive, because a fake exists to exercise the happy path; pass
    ``capabilities`` to test what happens when a model does *not* support something. The fake
    enforces declared capabilities exactly as a real adapter must, so a test cannot rely on a
    request a real model would refuse.
    """

    def __init__(
        self,
        replies: Sequence[ModelReply] = (),
        *,
        name: str = "fake",
        model: str = DEFAULT_FAKE_MODEL,
        capabilities: ModelCapabilities | None = None,
        health: ModelHealth | None = None,
        embed_error: BaseException | None = None,
    ) -> None:
        self._replies = tuple(replies) or (ModelReply.ok("fake reply"),)
        self._name = name
        self._model = model
        self._capabilities = capabilities or ModelCapabilities(
            tools=True, structured_output=True, streaming=True, embeddings=True
        )
        self._health = health
        self._calls = 0
        self._cancellations = 0
        self.requests: list[ChatRequest] = []
        self.embed_error = embed_error

    @property
    def name(self) -> str:
        """Return the fake provider's name."""
        return self._name

    @property
    def model(self) -> str:
        """Return the fake provider's model."""
        return self._model

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return the capabilities this fake claims."""
        return self._capabilities

    @property
    def calls(self) -> int:
        """How many chat calls have been made."""
        return self._calls

    @property
    def observed_cancellations(self) -> int:
        """How many calls observed cancellation while they were waiting."""
        return self._cancellations

    def reset(self) -> None:
        """Forget the counters and recorded requests so one fake can serve several scenarios."""
        self._calls = 0
        self._cancellations = 0
        self.requests.clear()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Return the next scripted reply."""
        self._check_capabilities(request)
        reply = self._next_reply()
        self.requests.append(request)
        await self._wait(reply.delay)
        if reply.error is not None:
            raise reply.error
        return ChatResponse(
            message=Message.assistant(reply.content, tool_calls=reply.tool_calls),
            model=reply.model,
            usage=reply.usage,
            finish_reason=reply.finish_reason,
        )

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Stream the next scripted reply."""
        self._check_capabilities(request)
        reply = self._next_reply()
        self.requests.append(request)
        pieces = reply.chunks or ((reply.content,) if reply.content else ())
        if reply.error is not None:
            await self._wait(reply.delay)
            raise reply.error
        for piece in pieces:
            await self._wait(reply.delay)
            yield ChatChunk(content=piece, done=False, model=reply.model)
        yield ChatChunk(content="", done=True, model=reply.model, usage=reply.usage)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Return deterministic pseudo-embeddings derived from the inputs."""
        if not self._capabilities.embeddings:
            raise AIUnsupportedCapabilityError(
                "this fake provider does not claim embedding support",
                capability="embeddings",
                model=self._model,
            )
        if self.embed_error is not None:
            raise self.embed_error
        return EmbeddingResponse(
            model=request.model or self._model,
            embeddings=tuple(_fake_vector(text) for text in request.inputs),
        )

    async def health(self) -> ModelHealth:
        """Return the scripted readiness, or a ready result by default."""
        return self._health or ModelHealth(status=ModelStatus.READY, model=self._model)

    def _next_reply(self) -> ModelReply:
        reply = self._replies[min(self._calls, len(self._replies) - 1)]
        self._calls += 1
        return reply

    def _check_capabilities(self, request: ChatRequest) -> None:
        if request.tools and not self._capabilities.tools:
            raise AIUnsupportedCapabilityError(
                "this fake provider does not claim tool support",
                capability="tools",
                model=self._model,
            )
        if request.response_schema is not None and not self._capabilities.structured_output:
            raise AIUnsupportedCapabilityError(
                "this fake provider does not claim structured output support",
                capability="structured_output",
                model=self._model,
            )

    async def _wait(self, delay: float) -> None:
        if not delay:
            return
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self._cancellations += 1
            raise


def _fake_vector(text: str) -> tuple[float, ...]:
    """Return a deterministic, stable vector for ``text``.

    It is plumbing, not semantics: use it to assert that embeddings travel intact, never to measure
    similarity.
    """
    length = len(text)
    checksum = sum(ord(character) for character in text)
    words = len(text.split())
    vowels = sum(1 for character in text.lower() if character in "aeiou")
    return (float(length), float(checksum), float(words), float(vowels))
