"""Provider-neutral AI contracts.

Nothing here names a vendor. A request describes messages, a budget, an optional response schema,
and optional tools; a response describes the model's message, its usage, and a normalized finish
reason. Provider adapters translate in both directions and keep their own wire formats to
themselves.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Protocol, runtime_checkable

from xyberos.ai.schema import check_schema
from xyberos.errors import AIRequestError


def _freeze(values: Mapping[str, object], *, location: str) -> Mapping[str, object]:
    if not isinstance(values, Mapping):
        raise AIRequestError(f"{location} must be a mapping, got {type(values).__name__}")
    return MappingProxyType(dict(values))


class Role(str, Enum):
    """Who produced a message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FinishReason(str, Enum):
    """Why a model stopped, normalized across providers.

    ``REFUSAL`` is only used when a provider reports a refusal explicitly; Xyberos never infers one
    from response text.
    """

    STOP = "stop"
    LENGTH = "length"
    TOOL_CALLS = "tool_calls"
    REFUSAL = "refusal"
    OTHER = "other"


@dataclass(frozen=True)
class ToolCall:
    """A tool invocation a model asked for.

    A provider adapter parses and normalizes these; it never executes one.
    """

    name: str
    arguments: Mapping[str, object] = field(default_factory=dict)
    call_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise AIRequestError("a tool call needs a non-empty tool name")
        object.__setattr__(
            self, "arguments", _freeze(self.arguments, location=f"arguments of tool {self.name!r}")
        )


@dataclass(frozen=True)
class Message:
    """One conversation entry.

    Content is text only. Multimodal parts are deliberately out of scope for this release.
    """

    role: Role
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, Role):
            raise AIRequestError(f"role must be a Role, got {type(self.role).__name__}")
        if not isinstance(self.content, str):
            raise AIRequestError("message content must be a string")
        if self.role is Role.TOOL and not self.tool_name:
            raise AIRequestError("a tool message must name the tool it answers")

    @classmethod
    def system(cls, content: str) -> Message:
        """Return a system message."""
        return cls(role=Role.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> Message:
        """Return a user message."""
        return cls(role=Role.USER, content=content)

    @classmethod
    def assistant(cls, content: str = "", *, tool_calls: tuple[ToolCall, ...] = ()) -> Message:
        """Return an assistant message, optionally carrying requested tool calls."""
        return cls(role=Role.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, tool_name: str, content: str) -> Message:
        """Return the result of a tool call."""
        return cls(role=Role.TOOL, content=content, tool_name=tool_name)


@dataclass(frozen=True)
class Usage:
    """Token accounting for one call, or the sum of several."""

    input_tokens: int = 0
    output_tokens: int = 0

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise AIRequestError("token counts cannot be negative")

    @property
    def total_tokens(self) -> int:
        """Return the reported tokens together."""
        return self.input_tokens + self.output_tokens

    def combined(self, other: Usage) -> Usage:
        """Return the sum of two usage reports, as a tool loop produces."""
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )

    def __add__(self, other: Usage) -> Usage:
        return self.combined(other)


@dataclass(frozen=True)
class ModelCapabilities:
    """What a model claims to support.

    Conservative by default. A provider API accepting a request field does not mean the model
    honours it, so an adapter refuses an undeclared capability instead of sending a request that may
    be silently ignored.
    """

    tools: bool = False
    structured_output: bool = False
    streaming: bool = True
    embeddings: bool = False


class ModelStatus(str, Enum):
    """The readiness of a provider and its configured model."""

    READY = "ready"
    UNREACHABLE = "unreachable"
    MODEL_UNAVAILABLE = "model_unavailable"
    UNHEALTHY = "unhealthy"


@dataclass(frozen=True)
class ModelHealth:
    """The outcome of a readiness check.

    A health check reports problems instead of raising them: distinguishing an unreachable service
    from a missing model is its whole purpose.
    """

    status: ModelStatus
    model: str
    detail: str = ""
    provider_version: str | None = None

    @property
    def ready(self) -> bool:
        """Whether the provider can serve the configured model."""
        return self.status is ModelStatus.READY


@dataclass(frozen=True)
class ToolSpec:
    """A tool declaration that can be offered to a model.

    ``parameters`` describes the arguments as a JSON Schema subset. It is checked when the spec is
    built, so an unusable declaration fails here instead of at call time.
    """

    name: str
    description: str = ""
    parameters: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise AIRequestError("a tool specification needs a non-empty name")
        if not isinstance(self.description, str):
            raise AIRequestError(f"the description of tool {self.name!r} must be a string")
        parameters = _freeze(self.parameters, location=f"parameters of tool {self.name!r}")
        check_schema(parameters, location=f"parameters of tool {self.name!r}")
        object.__setattr__(self, "parameters", parameters)


@dataclass(frozen=True)
class ChatRequest:
    """A provider-neutral chat request."""

    messages: tuple[Message, ...]
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stop: tuple[str, ...] = ()
    response_schema: Mapping[str, object] | None = None
    tools: tuple[ToolSpec, ...] = ()
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise AIRequestError("a chat request needs at least one message")
        for message in self.messages:
            if not isinstance(message, Message):
                raise AIRequestError(
                    f"messages must be Message values, got {type(message).__name__}"
                )
        if self.temperature is not None and not 0.0 <= self.temperature <= 2.0:
            raise AIRequestError("temperature must be between 0 and 2")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise AIRequestError("max_tokens must be at least 1")
        if self.timeout is not None and self.timeout <= 0:
            raise AIRequestError("timeout must be greater than zero")
        if self.response_schema is not None:
            schema = _freeze(self.response_schema, location="response_schema")
            check_schema(schema, location="response_schema")
            object.__setattr__(self, "response_schema", schema)


@dataclass(frozen=True)
class ChatResponse:
    """A completed chat call.

    ``structured`` holds the parsed and validated payload whenever the request asked for a response
    schema; ``message.content`` keeps the model's raw text either way.
    """

    message: Message
    model: str
    usage: Usage = Usage()
    finish_reason: FinishReason | None = None
    structured: object | None = None
    rounds: int = 1


@dataclass(frozen=True)
class ChatChunk:
    """One piece of a streaming chat response."""

    content: str
    done: bool = False
    model: str | None = None
    usage: Usage | None = None


@dataclass(frozen=True)
class EmbeddingRequest:
    """A provider-neutral embedding request."""

    inputs: tuple[str, ...]
    model: str | None = None
    timeout: float | None = None

    def __post_init__(self) -> None:
        if not self.inputs:
            raise AIRequestError("an embedding request needs at least one input")
        if any(not isinstance(item, str) or not item for item in self.inputs):
            raise AIRequestError("embedding inputs must be non-empty strings")
        if self.timeout is not None and self.timeout <= 0:
            raise AIRequestError("timeout must be greater than zero")


@dataclass(frozen=True)
class EmbeddingResponse:
    """Embeddings for one request, in the order the inputs were given."""

    model: str
    embeddings: tuple[tuple[float, ...], ...]
    usage: Usage = Usage()

    @property
    def dimensions(self) -> int | None:
        """Return the vector width, or ``None`` when the provider returned nothing."""
        return len(self.embeddings[0]) if self.embeddings else None


@runtime_checkable
class ChatModel(Protocol):
    """A provider that can hold a chat conversation."""

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return the capabilities this model claims."""
        ...

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Return one completed response."""
        ...

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Stream a response as it is produced."""
        ...


@runtime_checkable
class EmbeddingModel(Protocol):
    """A provider that can embed text."""

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return the capabilities this model claims."""
        ...

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Return embeddings for the requested inputs."""
        ...


@runtime_checkable
class ModelProvider(ChatModel, EmbeddingModel, Protocol):
    """A complete provider: chat, streaming, embeddings, and a readiness check.

    A provider that owns a connection pool should also expose ``async def aclose()`` so the
    application lifecycle can release it.
    """

    @property
    def name(self) -> str:
        """Return the adapter's name, used in errors and events."""
        ...

    async def health(self) -> ModelHealth:
        """Return the readiness of the provider and its configured model."""
        ...
