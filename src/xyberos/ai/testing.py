"""A deterministic AI provider for tests.

Nothing here touches a network or a vendor SDK. Replies play in order and the last one repeats, so
an "always rate limited" provider and a "fails once, then answers" provider are both one line. Every
scenario the facade must survive — delays, rate limits, transient faults, malformed payloads,
schema-invalid payloads, refusals, timeouts, and cancellation — is a scripted reply.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable, Mapping, Sequence
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
    ModelProvider,
    ModelStatus,
    Role,
    ToolCall,
    ToolSpec,
    Usage,
)
from xyberos.ai.schema import validate_payload
from xyberos.errors import (
    AIRateLimitError,
    AIRequestError,
    AISchemaError,
    AITimeoutError,
    AITransportError,
    AIUnsupportedCapabilityError,
)

__all__ = [
    "DEFAULT_FAKE_MODEL",
    "FakeModelProvider",
    "ModelReply",
    "assert_embedding_provider_contract",
    "assert_model_provider_contract",
]

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
        if not self._capabilities.streaming:
            raise AIUnsupportedCapabilityError(
                "this fake provider does not claim streaming support",
                capability="streaming",
                model=self._model,
            )
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


_NAME_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
    "additionalProperties": False,
}

_LOOKUP_TOOL = ToolSpec(
    name="lookup",
    description="Look up a topic and return a note about it.",
    parameters={
        "type": "object",
        "properties": {"topic": {"type": "string"}},
        "required": ["topic"],
        "additionalProperties": False,
    },
)


_CANCELLATION_GRACE = 0.01
"""How long a request is given to be in flight before the cancellation check cancels it."""


async def assert_model_provider_contract(
    provider: ModelProvider,
    *,
    chat_prompt: str = "Reply with the single word: ok",
    structured_prompt: str = 'Reply with JSON only and no prose: {"name": "Ada"}',
    tool_prompt: str = "Use the lookup tool to find the topic 'rain'.",
    schema: Mapping[str, object] | None = None,
    tool: ToolSpec | None = None,
) -> tuple[str, ...]:
    """Check that ``provider`` behaves the way :class:`~xyberos.ai.contracts.ModelProvider` says.

    This is the suite an adapter author outside this project runs against their own implementation —
    the same claims are checked here as against the shipped Ollama adapter, so "we support a
    different model backend" means evidence rather than intent. It raises ``AssertionError`` naming
    the check that failed, so it is usable from pytest, an ordinary script, or another test runner.

    Two properties make it work against a live model rather than only against a fake. Every check is
    *structural* — a reply has an assistant role, usage adds up, a structured payload matches the
    schema it was given — never a comparison against expected text, because the same prompt does not
    produce the same words twice. And every capability claim is checked from **both sides**: a
    capability the provider claims must work, and one it does not claim must be refused with
    :class:`~xyberos.errors.AIUnsupportedCapabilityError` rather than attempted. Claim nothing you
    cannot do, and you pass.

    ``prompt`` defaults are written to be answerable by a small model. A caller with a model that
    needs more coaxing — a live one, typically — passes its own prompts and schema.

    The check that usage is reported rather than guessed is a real requirement, not a formality: the
    facade's default logging policy keeps usage metadata and discards content, so a provider that
    reports no tokens removes the only number it is trusted to supply.
    """
    active_schema = dict(_NAME_SCHEMA if schema is None else schema)
    active_tool = _LOOKUP_TOOL if tool is None else tool
    checked: list[str] = []

    health = await provider.health()
    if not isinstance(health, ModelHealth):
        raise AssertionError(f"health() returned {type(health).__name__}, not a ModelHealth")
    if not health.ready:
        raise AssertionError(
            f"health() reports {health.status.value} for {health.model!r}. "
            f"The suite needs a ready provider; its detail was: {health.detail or 'none given'}"
        )
    checked.append("health() reports a ready provider")

    capabilities = provider.capabilities
    if not isinstance(capabilities, ModelCapabilities):
        raise AssertionError(f"capabilities returned {capabilities!r}, not ModelCapabilities")
    if not provider.name:
        raise AssertionError("the provider did not report a name")
    checked.append("name and capabilities are declared")

    chat_request = ChatRequest(messages=(Message.user(chat_prompt),))
    response = await provider.chat(chat_request)
    if not isinstance(response, ChatResponse):
        raise AssertionError(f"chat() returned {type(response).__name__}, not a ChatResponse")
    if response.message.role is not Role.ASSISTANT:
        raise AssertionError("chat() returned a message that is not from the assistant")
    if not response.message.content and not response.message.tool_calls:
        raise AssertionError("chat() returned neither content nor a tool call")
    if not response.model:
        raise AssertionError("chat() did not report which model answered")
    if response.finish_reason is not None and not isinstance(response.finish_reason, FinishReason):
        raise AssertionError(
            f"chat() reported an unusable finish_reason: {response.finish_reason!r}"
        )
    checked.append("chat() returns an assistant message with a model and a finish reason")

    usage = response.usage
    if not isinstance(usage, Usage):
        raise AssertionError(f"chat() reported usage {usage!r}, not a Usage")
    if usage.total_tokens != usage.input_tokens + usage.output_tokens:
        raise AssertionError(f"chat() reported usage that does not add up: {usage!r}")
    if usage.total_tokens < 1:
        raise AssertionError(
            "chat() reported no tokens at all; the contract requires usage to be reported, "
            "not guessed or omitted"
        )
    checked.append("usage is reported and adds up")

    if capabilities.streaming:
        pieces: list[str] = []
        terminals = 0
        async for chunk in provider.stream(chat_request):
            if not isinstance(chunk, ChatChunk):
                raise AssertionError(f"stream() yielded {type(chunk).__name__}, not a ChatChunk")
            if chunk.done:
                terminals += 1
            else:
                pieces.append(chunk.content)
        if terminals != 1:
            raise AssertionError(f"stream() ended with {terminals} terminal chunks, not one")
        if not "".join(pieces):
            raise AssertionError("stream() yielded no content at all")
        checked.append("stream() yields content and exactly one terminal chunk")
    else:
        try:
            await _first_chunk(provider.stream(chat_request))
        except AIUnsupportedCapabilityError:
            checked.append("stream() refuses when streaming is not claimed")
        else:
            raise AssertionError("stream() answered a model that does not claim streaming")

    structured_request = ChatRequest(
        messages=(Message.user(structured_prompt),), response_schema=active_schema
    )
    if capabilities.structured_output:
        reply = await provider.chat(structured_request)
        try:
            payload = json.loads(reply.message.content)
        except (TypeError, ValueError) as error:
            raise AssertionError(
                "the provider claims structured output but returned content that is not JSON: "
                f"{reply.message.content[:80]!r}"
            ) from error
        try:
            validate_payload(payload, active_schema, location="the structured reply")
        except (AISchemaError, AIRequestError) as error:
            raise AssertionError(
                "the provider claims structured output but its reply does not match the schema it "
                f"was given: {error}"
            ) from error
        checked.append("structured output honours the requested schema")
    else:
        try:
            await provider.chat(structured_request)
        except AIUnsupportedCapabilityError:
            checked.append("structured output is refused when it is not claimed")
        else:
            raise AssertionError("a model that does not claim structured output answered anyway")

    tool_request = ChatRequest(messages=(Message.user(tool_prompt),), tools=(active_tool,))
    if capabilities.tools:
        reply = await provider.chat(tool_request)
        for call in reply.message.tool_calls:
            if not isinstance(call, ToolCall):
                raise AssertionError(f"a tool call was reported as {type(call).__name__}")
            if call.name != active_tool.name:
                raise AssertionError(
                    f"the provider returned a call for {call.name!r}, which is not the tool it "
                    f"was given ({active_tool.name!r})"
                )
            if not isinstance(call.arguments, Mapping):
                raise AssertionError(f"the arguments of {call.name!r} are not a mapping")
        checked.append("a tool-calling request is accepted and every call names a declared tool")
    else:
        try:
            await provider.chat(tool_request)
        except AIUnsupportedCapabilityError:
            checked.append("tool use is refused when it is not claimed")
        else:
            raise AssertionError("a model that does not claim tool support accepted tools anyway")

    task = asyncio.create_task(provider.chat(chat_request))
    await asyncio.sleep(_CANCELLATION_GRACE)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        checked.append("cancellation propagates instead of being swallowed")
    else:
        # Honest rather than flaky: a provider that finished inside the grace period had nothing to
        # cancel, so the check reports that instead of asserting a race it cannot win.
        checked.append("cancellation was not observed: the provider answered immediately")

    return tuple(checked)


async def assert_embedding_provider_contract(
    provider: ModelProvider,
    *,
    inputs: Sequence[str] = ("first input", "second, different input"),
) -> tuple[str, ...]:
    """Check an embedding provider's half of the contract, and report what ran.

    Split from :func:`assert_model_provider_contract` because a provider may legitimately implement
    only one half: ``capabilities.embeddings`` is the switch, and a provider that leaves it false is
    checked for refusing rather than for answering.
    """
    checked: list[str] = []
    request = EmbeddingRequest(inputs=tuple(inputs))

    if not provider.capabilities.embeddings:
        try:
            await provider.embed(request)
        except AIUnsupportedCapabilityError:
            checked.append("embed() refuses when embedding support is not claimed")
        else:
            raise AssertionError(
                "a provider that does not claim embedding support answered an embed call"
            )
        return tuple(checked)

    response = await provider.embed(request)
    if not isinstance(response, EmbeddingResponse):
        raise AssertionError(
            f"embed() returned {type(response).__name__}, not an EmbeddingResponse"
        )
    if len(response.embeddings) != len(inputs):
        raise AssertionError(
            f"embed() returned {len(response.embeddings)} vectors for {len(inputs)} inputs"
        )
    widths = {len(vector) for vector in response.embeddings}
    if len(widths) != 1 or 0 in widths:
        raise AssertionError(f"the vectors are not all one non-zero width: {sorted(widths)}")
    if response.dimensions != next(iter(widths)):
        raise AssertionError("dimensions() disagrees with the vectors it returned")
    if not response.model:
        raise AssertionError("embed() did not report which model answered")
    if response.usage.total_tokens != response.usage.input_tokens + response.usage.output_tokens:
        raise AssertionError(f"embed() reported usage that does not add up: {response.usage!r}")
    checked.append("embed() returns one vector per input, all of one non-zero width")

    return tuple(checked)


async def _first_chunk(chunks: AsyncIterator[ChatChunk]) -> ChatChunk:
    """Return the first chunk, so a refusal raised before any yield surfaces here."""
    async for chunk in chunks:
        return chunk
    raise AssertionError("stream() yielded no chunks at all")
