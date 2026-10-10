"""The provider-neutral AI facade.

The facade owns everything that must not depend on a vendor: capability checks, the request budget,
structured-output validation, the bounded tool loop, usage accounting, and the logging policy. A
provider adapter owns its wire format and nothing more.

Two policies are deliberate. The facade never retries: it classifies failures so the caller's retry
policy — a workflow step's ``Retry``, for instance — decides. And logging records metadata only
unless content capture is explicitly turned on.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from dataclasses import dataclass, replace
from logging import Logger, getLogger

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
    ToolCall,
    Usage,
)
from xyberos.ai.schema import validate_payload
from xyberos.ai.tools import ToolResult, ToolSet
from xyberos.errors import (
    AIConfigurationError,
    AIInvalidPayloadError,
    AIRefusalError,
    AIRequestError,
    AISchemaError,
    AITimeoutError,
    AIToolError,
    AIUnsupportedCapabilityError,
)
from xyberos.runtime.context import get_deadline

DEFAULT_LOGGER_NAME = "xyberos.ai"
_REDACTED = "[redacted]"
_NO_PAYLOAD = object()
"""Marker distinguishing "no structured payload was requested" from a payload that is ``null``."""


@dataclass(frozen=True)
class LoggingPolicy:
    """How much of an AI call may reach the logs.

    The default records metadata only: provider, model, message and tool counts, timings, and token
    usage. Prompts and completions are captured only when a caller opts in, and even then they are
    truncated and passed through literal redaction first.
    """

    capture_content: bool = False
    max_content_length: int = 200
    redact: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.max_content_length < 1:
            raise AIConfigurationError("max_content_length must be at least 1")

    @classmethod
    def metadata_only(cls) -> LoggingPolicy:
        """Return the default policy, which never records content."""
        return cls()

    @classmethod
    def capturing(
        cls, *, max_content_length: int = 200, redact: Iterable[str] = ()
    ) -> LoggingPolicy:
        """Return a policy that records truncated, redacted content."""
        return cls(
            capture_content=True,
            max_content_length=max_content_length,
            redact=tuple(redact),
        )

    def apply(self, content: str) -> str:
        """Return ``content`` with every configured secret removed and then truncated."""
        redacted = content
        for secret in self.redact:
            if secret:
                redacted = redacted.replace(secret, _REDACTED)
        if len(redacted) > self.max_content_length:
            return f"{redacted[: self.max_content_length]}..."
        return redacted


class AIFacade:
    """Turn a provider into the framework's AI capability.

    .. code-block:: python

        facade = AIFacade(provider)
        response = await facade.chat(ChatRequest(messages=(Message.user("Hi"),)))
    """

    def __init__(
        self,
        provider: object,
        *,
        logging_policy: LoggingPolicy | None = None,
        logger: Logger | None = None,
    ) -> None:
        if provider is None:
            raise AIConfigurationError("an AI facade needs a provider")
        if not callable(getattr(provider, "chat", None)) and not callable(
            getattr(provider, "embed", None)
        ):
            raise AIConfigurationError(
                "an AI provider must implement chat() or embed(), and expose capabilities"
            )
        self._provider = provider
        self._policy = logging_policy or LoggingPolicy()
        self._logger = logger or getLogger(DEFAULT_LOGGER_NAME)

    @property
    def provider(self) -> object:
        """Return the wrapped provider."""
        return self._provider

    @property
    def name(self) -> str:
        """Return the provider's name."""
        return str(getattr(self._provider, "name", type(self._provider).__name__))

    @property
    def model(self) -> str:
        """Return the provider's configured model, or an empty string when it has none."""
        return str(getattr(self._provider, "model", "") or "")

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return the capabilities the provider claims."""
        capabilities = getattr(self._provider, "capabilities", None)
        if not isinstance(capabilities, ModelCapabilities):
            raise AIUnsupportedCapabilityError(
                "the AI provider does not declare capabilities, so no AI feature can be trusted",
                capability="capabilities",
                model=self.model,
            )
        return capabilities

    @property
    def logging_policy(self) -> LoggingPolicy:
        """Return the logging policy in force."""
        return self._policy

    async def aclose(self) -> None:
        """Close the wrapped provider when it owns resources.

        The facade is usually the object an application registers, so it releases whatever its
        provider holds — an HTTP connection pool, for instance — and does nothing when the provider
        has nothing to release.
        """
        close = getattr(self._provider, "aclose", None)
        if close is not None:
            await close()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Run one chat call and validate the response before returning it."""
        self._check_request(request)
        budget = self._budget(request.timeout)
        started = time.monotonic()
        response = await self._call_provider(request, budget)
        duration = time.monotonic() - started
        if response.finish_reason is FinishReason.REFUSAL:
            self._log_call(request, response, duration=duration, outcome="refused")
            raise AIRefusalError(f"the model {self.model or '<unset>'} refused the request")
        structured = self._validated_payload(request, response)
        self._log_call(request, response, duration=duration, outcome="ok")
        if structured is _NO_PAYLOAD:
            return response
        return replace(response, structured=structured)

    async def structured(self, request: ChatRequest) -> object:
        """Run a call that must produce a schema-valid payload, and return that payload."""
        if request.response_schema is None:
            raise AIRequestError("a structured call needs a response_schema")
        response = await self.chat(request)
        if response.structured is None:
            raise AISchemaError(
                "the response carried no structured payload; a response that requests tools is "
                "never validated against a schema"
            )
        return response.structured

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Stream one response, enforcing the request budget between chunks.

        Streaming carries content only: tools and response schemas are rejected, because a partially
        validated structured payload is not something a caller can act on. The capability checks run
        here rather than on first iteration, so a misconfiguration fails at the call site.
        """
        if request.tools:
            raise AIRequestError("a streaming request cannot offer tools")
        if request.response_schema is not None:
            raise AIRequestError("a streaming request cannot ask for a response schema")
        self._require_method("stream", capability="streaming")
        if not self.capabilities.streaming:
            raise AIUnsupportedCapabilityError(
                "this model does not claim streaming support",
                capability="streaming",
                model=self.model,
            )
        return self._stream(request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Return embeddings for the requested inputs."""
        self._require_method("embed", capability="embeddings")
        if not self.capabilities.embeddings:
            raise AIUnsupportedCapabilityError(
                "no embedding model is configured for this provider",
                capability="embeddings",
                model=self.model,
            )
        budget = self._budget(request.timeout)
        started = time.monotonic()
        response = await self._await_budget(
            budget,
            lambda: self._provider.embed(request),  # type: ignore[attr-defined]
        )
        if not isinstance(response, EmbeddingResponse):
            raise AIInvalidPayloadError(
                f"the {self.name} adapter returned {type(response).__name__} instead of an "
                "EmbeddingResponse"
            )
        self._logger.debug(
            "ai embed provider=%s model=%s inputs=%d dimensions=%s duration=%.6f",
            self.name,
            response.model or self.model,
            len(request.inputs),
            response.dimensions,
            time.monotonic() - started,
        )
        return response

    async def health(self) -> ModelHealth:
        """Return the provider's readiness, when it reports one."""
        self._require_method("health", capability="health")
        health = await self._provider.health()  # type: ignore[attr-defined]
        if not isinstance(health, ModelHealth):
            raise AIInvalidPayloadError(
                f"the {self.name} adapter returned {type(health).__name__} instead of a ModelHealth"
            )
        return health

    async def invoke_tools(
        self, calls: Iterable[ToolCall] | ChatResponse, *, tools: ToolSet
    ) -> tuple[ToolResult, ...]:
        """Validate and run requested tool calls against an explicit allowlist.

        A call outside the allowlist raises :class:`~xyberos.errors.AIToolError`; invalid arguments
        and handler failures come back as failed results so a caller can hand them to the model.
        """
        requested = calls.message.tool_calls if isinstance(calls, ChatResponse) else tuple(calls)
        return await tools.invoke_all(requested)

    async def chat_with_tools(
        self, request: ChatRequest, *, tools: ToolSet, max_rounds: int = 3
    ) -> ChatResponse:
        """Run a bounded model-tool loop and return the final answer.

        Long-lived orchestration belongs in a workflow; this loop is deliberately short, bounded by
        ``max_rounds``, and it only ever runs tools from the given allowlist.
        """
        if max_rounds < 1:
            raise AIRequestError("max_rounds must be at least 1")
        if not self.capabilities.tools:
            raise AIUnsupportedCapabilityError(
                "this model does not claim tool support",
                capability="tools",
                model=self.model,
            )
        messages: list[Message] = list(request.messages)
        usage = Usage()
        for round_number in range(1, max_rounds + 1):
            current = replace(request, messages=tuple(messages), tools=tools.specs)
            response = await self.chat(current)
            usage = usage + response.usage
            calls = response.message.tool_calls
            if not calls:
                return replace(response, usage=usage, rounds=round_number)
            if round_number == max_rounds:
                raise AIToolError(
                    f"the model asked for {calls[0].name!r} after {max_rounds} round(s), which is "
                    "the configured limit; raise max_rounds or move the orchestration into a "
                    "workflow",
                    tool=calls[0].name,
                )
            messages.append(response.message)
            for result in await tools.invoke_all(calls):
                messages.append(Message.tool_result(result.tool, result.render()))
        raise AssertionError("unreachable: the tool loop always returns or raises")

    async def _call_provider(self, request: ChatRequest, budget: float | None) -> ChatResponse:
        response = await self._await_budget(
            budget,
            lambda: self._provider.chat(request),  # type: ignore[attr-defined]
        )
        if not isinstance(response, ChatResponse):
            raise AIInvalidPayloadError(
                f"the {self.name} adapter returned {type(response).__name__} instead of a "
                "ChatResponse"
            )
        return response

    async def _await_budget(
        self, budget: float | None, call: Callable[[], Awaitable[object]]
    ) -> object:
        """Await one provider call, enforcing ``budget`` seconds when it is set."""
        if budget is not None and budget <= 0:
            raise AITimeoutError(
                f"no time left for the {self.name} request: its budget was already exhausted"
            )
        try:
            if budget is None:
                return await call()
            return await asyncio.wait_for(call(), timeout=budget)
        except asyncio.TimeoutError as error:
            raise AITimeoutError(
                f"the {self.name} request exceeded its budget of {budget:g}s"
            ) from error

    async def _stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        budget = self._budget(request.timeout)
        if budget is not None and budget <= 0:
            raise AITimeoutError(
                f"no time left for the {self.name} request: its budget was already exhausted"
            )
        expires_at = None if budget is None else time.monotonic() + budget
        iterator = self._provider.stream(request).__aiter__()  # type: ignore[attr-defined]
        try:
            while True:
                remaining = None if expires_at is None else expires_at - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise AITimeoutError(self._stream_timeout(budget))
                try:
                    if remaining is None:
                        chunk = await anext(iterator)
                    else:
                        chunk = await asyncio.wait_for(anext(iterator), timeout=remaining)
                except StopAsyncIteration:
                    return
                except asyncio.TimeoutError as error:
                    raise AITimeoutError(self._stream_timeout(budget)) from error
                if not isinstance(chunk, ChatChunk):
                    raise AIInvalidPayloadError(
                        f"the {self.name} adapter streamed {type(chunk).__name__} instead of a "
                        "ChatChunk"
                    )
                yield chunk
        finally:
            close = getattr(iterator, "aclose", None)
            if close is not None:
                await close()

    def _stream_timeout(self, budget: float | None) -> str:
        if budget is None:  # pragma: no cover - the budget is always set on this path
            return f"the {self.name} stream stopped early"
        return f"the {self.name} stream exceeded its budget of {budget:g}s"

    def _budget(self, request_timeout: float | None) -> float | None:
        """Return the seconds a call may take, honouring any deadline bound to the context."""
        deadline = get_deadline()
        if deadline is None:
            return request_timeout
        remaining = max(deadline - time.monotonic(), 0.0)
        return remaining if request_timeout is None else min(request_timeout, remaining)

    def _check_request(self, request: ChatRequest) -> None:
        self._require_method("chat", capability="chat")
        capabilities = self.capabilities
        if request.tools and not capabilities.tools:
            raise AIUnsupportedCapabilityError(
                "the request offers tools but this model does not claim tool support; declare the "
                "capability on the provider before relying on it",
                capability="tools",
                model=self.model,
            )
        if request.response_schema is not None and not capabilities.structured_output:
            raise AIUnsupportedCapabilityError(
                "the request asks for a response schema but this model does not claim structured "
                "output support; declare the capability on the provider before relying on it",
                capability="structured_output",
                model=self.model,
            )

    def _require_method(self, method: str, *, capability: str) -> None:
        if not callable(getattr(self._provider, method, None)):
            raise AIUnsupportedCapabilityError(
                f"the AI provider does not implement {method}()",
                capability=capability,
                model=self.model,
            )

    def _validated_payload(self, request: ChatRequest, response: ChatResponse) -> object:
        """Return the validated payload, or ``_NO_PAYLOAD`` when none was requested.

        A response that asks for tools is not validated: the schema describes the final answer,
        not a request to call a tool.
        """
        schema = request.response_schema
        if schema is None or response.message.tool_calls:
            return _NO_PAYLOAD
        try:
            payload = json.loads(response.message.content)
        except json.JSONDecodeError as error:
            raise AIInvalidPayloadError(
                f"the model returned content that is not JSON ({error.msg}); retry the call or "
                "adjust the prompt"
            ) from error
        validate_payload(payload, schema, location="the model response")
        return payload

    def _log_call(
        self, request: ChatRequest, response: ChatResponse, *, duration: float, outcome: str
    ) -> None:
        if not self._logger.isEnabledFor(logging.DEBUG):
            return
        self._logger.debug(
            "ai chat provider=%s model=%s outcome=%s messages=%d tools=%d schema=%s "
            "tool_calls=%d duration=%.6f input_tokens=%d output_tokens=%d",
            self.name,
            response.model or self.model,
            outcome,
            len(request.messages),
            len(request.tools),
            request.response_schema is not None,
            len(response.message.tool_calls),
            duration,
            response.usage.input_tokens,
            response.usage.output_tokens,
        )
        if not self._policy.capture_content:
            return
        for message in request.messages:
            self._logger.debug(
                "ai prompt role=%s content=%s",
                message.role.value,
                self._policy.apply(message.content),
            )
        self._logger.debug("ai completion content=%s", self._policy.apply(response.message.content))
