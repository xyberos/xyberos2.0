"""The Ollama adapter: the documented HTTP API behind the provider-neutral contracts.

Installed by the ``ollama`` extra. Xyberos never pulls, starts, stops, or upgrades a model, and it
keeps every Ollama request and response shape inside this module.

An injected ``httpx.AsyncClient`` is used as given and never closed, which is how tests drive the
adapter through ``httpx.MockTransport`` and how applications share a connection pool.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from logging import Logger, getLogger
from types import MappingProxyType
from urllib.parse import urlsplit

try:
    import httpx
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("ollama", error) from error

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
    ToolSpec,
    Usage,
)
from xyberos.config import _as_bool, _as_float
from xyberos.errors import (
    AIConfigurationError,
    AIInvalidPayloadError,
    AIModelNotFoundError,
    AIRateLimitError,
    AIRequestError,
    AITimeoutError,
    AITransportError,
    AIUnsupportedCapabilityError,
    ConfigurationError,
)

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL_ENV_HINT = "XYBEROS_AI__OLLAMA__MODEL"
CHAT_PATH = "/api/chat"
EMBED_PATH = "/api/embed"
SHOW_PATH = "/api/show"
VERSION_PATH = "/api/version"

# The newest Ollama feature this adapter depends on decides the floor: JSON-schema ``format``
# (structured output) shipped in 0.5.0, after batch ``/api/embed`` (0.2.6) and tool calling (0.3.0).
# A floor that is only documented is not a floor, so the adapter refuses a service below it.
MINIMUM_SUPPORTED_VERSION = "0.5.0"
_RESERVED_OPTION_KEYS = frozenset(
    {"model", "messages", "stream", "format", "tools", "keep_alive", "options", "input"}
)
_LOGGER_NAME = "xyberos.ai.ollama"
_SETTINGS_KEYS = frozenset(
    {
        "model",
        "base_url",
        "embedding_model",
        "timeout",
        "connect_timeout",
        "tools",
        "structured_output",
        "streaming",
        "minimum_version",
        "options",
    }
)


@dataclass(frozen=True)
class OllamaSettings:
    """Configuration for one Ollama adapter.

    ``model`` is required: Xyberos never chooses a model, and never downloads one. Capability claims
    are explicit and default to the conservative side, because Ollama accepting a request field does
    not mean the model honours it.
    """

    model: str
    base_url: str = DEFAULT_BASE_URL
    embedding_model: str | None = None
    timeout: float | None = 60.0
    connect_timeout: float | None = 5.0
    tools: bool = False
    structured_output: bool = False
    streaming: bool = True
    minimum_version: str = MINIMUM_SUPPORTED_VERSION
    options: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.model, str) or not self.model.strip():
            raise AIConfigurationError(
                "an Ollama adapter needs an explicit model: Xyberos never chooses a model for you, "
                f"so set it in configuration, for example {DEFAULT_MODEL_ENV_HINT}=llama3.2"
            )
        _validate_base_url(self.base_url)
        object.__setattr__(self, "base_url", self.base_url.rstrip("/"))
        object.__setattr__(
            self, "minimum_version", _validate_version(self.minimum_version, "minimum_version")
        )
        for label, value in (("timeout", self.timeout), ("connect_timeout", self.connect_timeout)):
            if value is not None and value <= 0:
                raise AIConfigurationError(f"{label} must be greater than zero, got {value!r}")
        if self.embedding_model is not None and not self.embedding_model.strip():
            raise AIConfigurationError("embedding_model must be a non-empty model name")
        object.__setattr__(self, "options", _freeze_options(self.options))

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return the capabilities these settings claim."""
        return ModelCapabilities(
            tools=self.tools,
            structured_output=self.structured_output,
            streaming=self.streaming,
            embeddings=self.embedding_model is not None,
        )

    @classmethod
    def from_mapping(
        cls, values: Mapping[str, object], *, location: str = "ai.ollama"
    ) -> OllamaSettings:
        """Build settings from a validated configuration section such as ``[ai.ollama]``."""
        if not isinstance(values, Mapping):
            raise AIConfigurationError(f"{location} must be a table/object")
        unknown = sorted(set(values) - _SETTINGS_KEYS)
        if unknown:
            supported = ", ".join(sorted(_SETTINGS_KEYS))
            raise AIConfigurationError(
                f"{location} has unknown setting(s): {', '.join(unknown)}; supported settings are: "
                f"{supported}"
            )
        if not values.get("model"):
            raise AIConfigurationError(
                f"{location}.model is required: Xyberos never chooses a model for you, so set it "
                f"in configuration, for example {DEFAULT_MODEL_ENV_HINT}=llama3.2"
            )
        options = values.get("options", {})
        if not isinstance(options, Mapping):
            raise AIConfigurationError(f"{location}.options must be a table/object")
        return cls(
            model=_text(values["model"], f"{location}.model"),
            base_url=_text(values.get("base_url", DEFAULT_BASE_URL), f"{location}.base_url"),
            embedding_model=_optional_text(
                values.get("embedding_model"), f"{location}.embedding_model"
            ),
            timeout=_optional_number(values.get("timeout"), f"{location}.timeout", default=60.0),
            connect_timeout=_optional_number(
                values.get("connect_timeout"), f"{location}.connect_timeout", default=5.0
            ),
            tools=_flag(values.get("tools"), f"{location}.tools", default=False),
            structured_output=_flag(
                values.get("structured_output"), f"{location}.structured_output", default=False
            ),
            streaming=_flag(values.get("streaming"), f"{location}.streaming", default=True),
            minimum_version=_text(
                values.get("minimum_version", MINIMUM_SUPPORTED_VERSION),
                f"{location}.minimum_version",
            ),
            options={str(key): value for key, value in options.items()},
        )


def _validate_base_url(base_url: object) -> None:
    """Reject anything that is not a plain http(s) URL, and never echo the value.

    Credentials are checked first, because the check that rejects them must win over the one that
    describes the value: a URL such as ``ftp://user:secret@host`` would otherwise be quoted in the
    message, which is exactly what the credential rule exists to prevent. No branch echoes the
    input for the same reason — a free-form string from configuration is the one thing here that may
    hold a password, so the messages state the expected shape instead.
    """
    if not isinstance(base_url, str) or not base_url.strip():
        raise AIConfigurationError("base_url must be a non-empty URL")
    parts = urlsplit(base_url)
    if parts.username or parts.password:
        raise AIConfigurationError(
            "base_url must not embed credentials, because they would reach logs and error messages"
        )
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise AIConfigurationError(
            f"base_url must be an http(s) URL with a host, for example {DEFAULT_BASE_URL}"
        )


def _validate_version(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AIConfigurationError(
            f"{label} must be a non-empty version such as {MINIMUM_SUPPORTED_VERSION}"
        )
    if _version_tuple(value.strip()) is None:
        raise AIConfigurationError(
            f"{label} must be a dotted numeric version such as {MINIMUM_SUPPORTED_VERSION}, "
            f"got {value!r}"
        )
    return value.strip()


def _version_tuple(value: str) -> tuple[int, ...] | None:
    """Return the numeric release part of a version, or ``None`` when it is not comparable.

    Ollama reports plain releases (``0.5.0``) but also pre-releases (``0.5.0-rc1``) and, in
    development builds, an opaque string. Only the leading dotted numbers are compared, and an
    unparseable version is treated as unknown rather than as too old: refusing to work against a
    service you cannot measure would be worse than the risk it guards.
    """
    head = value.split("-", 1)[0].split("+", 1)[0].strip()
    parts = head.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _version_is_below(reported: str, floor: str) -> bool:
    """Whether ``reported`` is an older release than ``floor``; ``False`` when incomparable."""
    left = _version_tuple(reported)
    right = _version_tuple(floor)
    if left is None or right is None:
        return False
    return left < right


def _freeze_options(options: object) -> Mapping[str, object]:
    if not isinstance(options, Mapping):
        raise AIConfigurationError("options must be a table/object")
    reserved = sorted({str(key) for key in options} & _RESERVED_OPTION_KEYS)
    if reserved:
        raise AIConfigurationError(
            f"options must not set reserved key(s): {', '.join(reserved)}; the adapter owns those "
            "fields so a setting cannot rewrite the request"
        )
    for key in options:
        if not isinstance(key, str) or not key.strip():
            raise AIConfigurationError("options keys must be non-empty strings")
    try:
        json.dumps(dict(options))
    except (TypeError, ValueError) as error:
        raise AIConfigurationError(f"options must be JSON-serializable: {error}") from error
    return MappingProxyType(dict(options))


class OllamaProvider:
    """An Ollama adapter implementing chat, streaming, embeddings, and readiness."""

    def __init__(
        self,
        settings: OllamaSettings,
        *,
        client: httpx.AsyncClient | None = None,
        logger: Logger | None = None,
    ) -> None:
        if not isinstance(settings, OllamaSettings):
            raise AIConfigurationError(f"expected OllamaSettings, got {type(settings).__name__}")
        self._settings = settings
        self._http = client
        self._owns_client = client is None
        self._logger = logger or getLogger(_LOGGER_NAME)
        # Filled by whichever call learns the service's release, so the floor costs one request per
        # adapter rather than one per call, and so an unmeasured service is never refused.
        self._reported_version: str | None = None

    @property
    def name(self) -> str:
        """Return the adapter name."""
        return "ollama"

    @property
    def model(self) -> str:
        """Return the configured chat model."""
        return self._settings.model

    @property
    def settings(self) -> OllamaSettings:
        """Return the settings this adapter was built with."""
        return self._settings

    @property
    def capabilities(self) -> ModelCapabilities:
        """Return the capabilities these settings claim."""
        return self._settings.capabilities

    async def aclose(self) -> None:
        """Close the client this adapter owns. An injected client is left alone."""
        if self._http is None or not self._owns_client:
            return
        client, self._http = self._http, None
        await client.aclose()

    def _floor_message(self, reported: str) -> str:
        return (
            f"Ollama {reported} is older than the supported minimum "
            f"{self._settings.minimum_version}: structured output, tool calling, and batch "
            "embeddings are only verified against that floor or newer. Upgrade Ollama, or lower "
            "minimum_version deliberately and accept that Xyberos does not test against it"
        )

    def _refuse_unsupported_service(self) -> None:
        """Refuse a request when the service is known to be below the supported floor.

        The version comes from a previous probe, so this never adds a round trip: an unmeasured
        service proceeds and lets Ollama answer for itself, while a service already known to be too
        old is refused with a reason instead of a confusing 4xx from inside the API.
        """
        reported = self._reported_version
        if reported is not None and _version_is_below(reported, self._settings.minimum_version):
            raise AIConfigurationError(self._floor_message(reported))

    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Return one completed chat response."""
        self._require_supported(request)
        self._refuse_unsupported_service()
        data = await self._post(CHAT_PATH, self._chat_payload(request, stream=False))
        return self._chat_response(data)

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        """Stream a chat response.

        Ollama streams content; this adapter therefore refuses tools and response schemas on a
        streaming request rather than streaming a payload nothing can validate yet.
        """
        self._require_supported(request)
        if not self._settings.capabilities.streaming:
            raise AIUnsupportedCapabilityError(
                f"the Ollama model {self._settings.model!r} is configured with streaming = false; "
                "enable it once you have confirmed the model supports streaming",
                capability="streaming",
                model=self._settings.model,
            )
        self._refuse_unsupported_service()
        if request.tools:
            raise AIRequestError("an Ollama streaming request cannot offer tools")
        if request.response_schema is not None:
            raise AIRequestError("an Ollama streaming request cannot ask for a response schema")
        return self._stream(request)

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Return embeddings for the requested inputs."""
        model = request.model or self._settings.embedding_model
        if not model:
            raise AIConfigurationError(
                "no embedding model is configured; set embedding_model on the Ollama settings, for "
                "example XYBEROS_AI__OLLAMA__EMBEDDING_MODEL=nomic-embed-text"
            )
        self._refuse_unsupported_service()
        data = await self._post(EMBED_PATH, {"model": model, "input": list(request.inputs)})
        return self._embedding_response(data, inputs=len(request.inputs), model=model)

    async def health(self) -> ModelHealth:
        """Report whether the service is reachable and the configured model is usable.

        A health check reports problems rather than raising them, and it validates declared
        capability claims against what the model itself reports. It also compares the service's
        reported release against the supported floor and remembers it, so a later request can be
        refused with a reason instead of failing inside Ollama.
        """
        client = self._client()
        version = await self._service_version(client)
        if version is None:
            return ModelHealth(
                status=ModelStatus.UNREACHABLE,
                model=self._settings.model,
                detail=(
                    f"the Ollama service at {self._settings.base_url} did not answer {VERSION_PATH}"
                ),
            )
        self._reported_version = version
        if _version_is_below(version, self._settings.minimum_version):
            return ModelHealth(
                status=ModelStatus.UNHEALTHY,
                model=self._settings.model,
                detail=self._floor_message(version),
                provider_version=version,
            )
        try:
            response = await client.post(SHOW_PATH, json={"model": self._settings.model})
        except httpx.HTTPError as error:
            return ModelHealth(
                status=ModelStatus.UNHEALTHY,
                model=self._settings.model,
                detail=f"the model could not be inspected ({type(error).__name__})",
                provider_version=version,
            )
        if response.status_code == 404:
            return ModelHealth(
                status=ModelStatus.MODEL_UNAVAILABLE,
                model=self._settings.model,
                detail=(
                    f"the model {self._settings.model!r} is not available on this service; pull it "
                    "yourself or configure another model, because Xyberos never pulls models"
                ),
                provider_version=version,
            )
        if response.status_code >= 400:
            return ModelHealth(
                status=ModelStatus.UNHEALTHY,
                model=self._settings.model,
                detail=f"Ollama answered {response.status_code} for {SHOW_PATH}",
                provider_version=version,
            )
        reported = _reported_capabilities(_safe_json(response))
        mismatch = self._capability_mismatch(reported)
        if mismatch:
            return ModelHealth(
                status=ModelStatus.UNHEALTHY,
                model=self._settings.model,
                detail=mismatch,
                provider_version=version,
            )
        return ModelHealth(
            status=ModelStatus.READY, model=self._settings.model, provider_version=version
        )

    async def _stream(self, request: ChatRequest) -> AsyncIterator[ChatChunk]:
        payload = self._chat_payload(request, stream=True)
        client = self._client()
        try:
            async with client.stream("POST", CHAT_PATH, json=payload) as response:
                if response.status_code >= 400:
                    await response.aread()
                    self._raise_for_status(response, CHAT_PATH)
                async for line in response.aiter_lines():
                    chunk = self._stream_chunk(line)
                    if chunk is not None:
                        yield chunk
        except httpx.TimeoutException as error:
            raise AITimeoutError("the Ollama stream timed out") from error
        except httpx.HTTPError as error:
            raise AITransportError(
                f"the Ollama service became unreachable during the stream: {type(error).__name__}"
            ) from error

    def _stream_chunk(self, line: str) -> ChatChunk | None:
        text = line.strip()
        if not text:
            return None
        data = _decode_object(text, source=f"a streamed line from {CHAT_PATH}")
        self._raise_for_error_field(data)
        message = data.get("message")
        content = message.get("content", "") if isinstance(message, Mapping) else ""
        if not isinstance(content, str):
            raise AIInvalidPayloadError("Ollama streamed a message whose content is not a string")
        done = data.get("done") is True
        usage = None
        if done:
            usage = Usage(
                input_tokens=_count(data.get("prompt_eval_count")),
                output_tokens=_count(data.get("eval_count")),
            )
        model = data.get("model")
        return ChatChunk(
            content=content,
            done=done,
            model=model if isinstance(model, str) and model else self._settings.model,
            usage=usage,
        )

    async def _post(self, path: str, payload: Mapping[str, object]) -> dict[str, object]:
        client = self._client()
        self._logger.debug("ollama call path=%s model=%s", path, payload.get("model"))
        try:
            response = await client.post(path, json=payload)
        except httpx.TimeoutException as error:
            raise AITimeoutError(f"the Ollama call to {path} timed out") from error
        except httpx.HTTPError as error:
            raise AITransportError(
                f"the Ollama service is unreachable: {type(error).__name__}"
            ) from error
        self._raise_for_status(response, path)
        data = _decode_object(response.text, source=f"the {path} response")
        self._raise_for_error_field(data)
        return data

    async def _service_version(self, client: httpx.AsyncClient) -> str | None:
        try:
            response = await client.get(VERSION_PATH)
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        version = _safe_json(response).get("version")
        return version if isinstance(version, str) and version else "unknown"

    def _chat_response(self, data: Mapping[str, object]) -> ChatResponse:
        message = data.get("message")
        if not isinstance(message, Mapping):
            raise AIInvalidPayloadError(f"the {CHAT_PATH} response has no message object")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise AIInvalidPayloadError("the Ollama message content is not a string")
        tool_calls = self._tool_calls(message.get("tool_calls"))
        model = data.get("model")
        return ChatResponse(
            message=Message.assistant(content, tool_calls=tool_calls),
            model=model if isinstance(model, str) and model else self._settings.model,
            usage=Usage(
                input_tokens=_count(data.get("prompt_eval_count")),
                output_tokens=_count(data.get("eval_count")),
            ),
            finish_reason=_finish_reason(data, tool_calls),
        )

    def _tool_calls(self, raw: object) -> tuple[ToolCall, ...]:
        if raw is None:
            return ()
        if isinstance(raw, str) or not isinstance(raw, Sequence):
            raise AIInvalidPayloadError("Ollama tool_calls must be an array")
        calls: list[ToolCall] = []
        for item in raw:
            if not isinstance(item, Mapping):
                raise AIInvalidPayloadError("every Ollama tool call must be an object")
            function = item.get("function")
            if not isinstance(function, Mapping):
                raise AIInvalidPayloadError("every Ollama tool call needs a function object")
            name = function.get("name")
            if not isinstance(name, str) or not name:
                raise AIInvalidPayloadError("every Ollama tool call needs a function name")
            calls.append(
                ToolCall(name=name, arguments=self._tool_arguments(function.get("arguments"), name))
            )
        return tuple(calls)

    def _tool_arguments(self, raw: object, name: str) -> dict[str, object]:
        if raw is None:
            return {}
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError as error:
                raise AIInvalidPayloadError(
                    f"Ollama returned tool arguments for {name!r} that are not JSON"
                ) from error
        if not isinstance(raw, Mapping):
            raise AIInvalidPayloadError(f"the arguments of tool {name!r} must be an object")
        return {str(key): value for key, value in raw.items()}

    def _embedding_response(
        self, data: Mapping[str, object], *, inputs: int, model: str
    ) -> EmbeddingResponse:
        raw = data.get("embeddings")
        if isinstance(raw, str) or not isinstance(raw, Sequence) or not raw:
            raise AIInvalidPayloadError(f"the {EMBED_PATH} response carries no embeddings")
        vectors: list[tuple[float, ...]] = []
        for item in raw:
            if isinstance(item, (str, bytes)) or not isinstance(item, Sequence):
                raise AIInvalidPayloadError("every Ollama embedding must be an array of numbers")
            vector = []
            for value in item:
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise AIInvalidPayloadError("Ollama returned a non-numeric embedding value")
                vector.append(float(value))
            vectors.append(tuple(vector))
        if len(vectors) != inputs:
            raise AIInvalidPayloadError(
                f"Ollama returned {len(vectors)} embedding(s) for {inputs} input(s)"
            )
        returned = data.get("model")
        return EmbeddingResponse(
            model=returned if isinstance(returned, str) and returned else model,
            embeddings=tuple(vectors),
            usage=Usage(input_tokens=_count(data.get("prompt_eval_count"))),
        )

    def _chat_payload(self, request: ChatRequest, *, stream: bool) -> dict[str, object]:
        options: dict[str, object] = dict(self._settings.options)
        if request.temperature is not None:
            options["temperature"] = request.temperature
        if request.max_tokens is not None:
            options["num_predict"] = request.max_tokens
        if request.stop:
            options["stop"] = list(request.stop)
        payload: dict[str, object] = {
            "model": request.model or self._settings.model,
            "messages": [_message_payload(message) for message in request.messages],
            "stream": stream,
        }
        if options:
            payload["options"] = options
        if request.response_schema is not None:
            payload["format"] = dict(request.response_schema)
        if request.tools:
            payload["tools"] = [_tool_payload(tool) for tool in request.tools]
        return payload

    def _require_supported(self, request: ChatRequest) -> None:
        capabilities = self._settings.capabilities
        if request.tools and not capabilities.tools:
            raise AIUnsupportedCapabilityError(
                f"the Ollama model {self._settings.model!r} is not configured with tool support; "
                "set tools = true for this model once you have confirmed the model supports them",
                capability="tools",
                model=self._settings.model,
            )
        if request.response_schema is not None and not capabilities.structured_output:
            raise AIUnsupportedCapabilityError(
                f"the Ollama model {self._settings.model!r} is not configured with structured "
                "output support; set structured_output = true once you have confirmed the model "
                "honours a JSON schema",
                capability="structured_output",
                model=self._settings.model,
            )

    def _capability_mismatch(self, reported: tuple[str, ...] | None) -> str:
        if reported is None:
            return ""
        if self._settings.tools and "tools" not in reported:
            return (
                f"this adapter is configured with tools = true, but the model reports these "
                f"capabilities: {', '.join(reported) or 'none'}"
            )
        return ""

    def _raise_for_status(self, response: httpx.Response, path: str) -> None:
        if response.status_code < 400:
            return
        detail = _error_text(response)
        status = response.status_code
        if status == 429:
            raise AIRateLimitError(f"Ollama rate limited the call to {path}: {detail}")
        if status == 404 and "not found" in detail.lower():
            raise AIModelNotFoundError(
                f"the model {self._settings.model!r} is not available on the Ollama service "
                f"({detail}); pull it yourself or configure another model",
                model=self._settings.model,
            )
        if status >= 500:
            raise AITransportError(f"Ollama answered {status} for {path}: {detail}")
        raise AIRequestError(f"Ollama rejected the call to {path} with {status}: {detail}")

    def _raise_for_error_field(self, data: Mapping[str, object]) -> None:
        """Turn a provider-reported error inside a successful response into a normalized error."""
        message = data.get("error")
        if message is None:
            return
        text = str(message)
        lowered = text.lower()
        if "not found" in lowered:
            raise AIModelNotFoundError(
                f"the model {self._settings.model!r} is not available on the Ollama service "
                f"({text}); pull it yourself or configure another model",
                model=self._settings.model,
            )
        if "rate limit" in lowered or "too many requests" in lowered:
            raise AIRateLimitError(f"Ollama rate limited the request: {text}")
        if any(word in lowered for word in ("loading", "try again", "unavailable", "timeout")):
            raise AITransportError(f"Ollama is temporarily unavailable: {text}")
        raise AIRequestError(f"Ollama reported an error it cannot retry: {text}")

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            timeout = httpx.Timeout(self._settings.timeout, connect=self._settings.connect_timeout)
            self._http = httpx.AsyncClient(base_url=self._settings.base_url, timeout=timeout)
            self._owns_client = True
        return self._http


def ollama_provider(
    settings: OllamaSettings, *, client: httpx.AsyncClient | None = None
) -> Callable[[], Awaitable[OllamaProvider]]:
    """Return a factory suitable for ``App.provide(ModelProvider, factory=..., eager=True)``."""

    async def factory() -> OllamaProvider:
        return OllamaProvider(settings, client=client)

    return factory


def _message_payload(message: Message) -> dict[str, object]:
    payload: dict[str, object] = {"role": message.role.value, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {"function": {"name": call.name, "arguments": dict(call.arguments)}}
            for call in message.tool_calls
        ]
    return payload


def _tool_payload(tool: ToolSpec) -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": dict(tool.parameters),
        },
    }


def _finish_reason(
    data: Mapping[str, object], tool_calls: tuple[ToolCall, ...]
) -> FinishReason | None:
    if tool_calls:
        return FinishReason.TOOL_CALLS
    reason = data.get("done_reason")
    if reason is None:
        return None
    if reason == "stop":
        return FinishReason.STOP
    if reason == "length":
        return FinishReason.LENGTH
    return FinishReason.OTHER


def _decode_object(text: str, *, source: str) -> dict[str, object]:
    try:
        data = json.loads(text)
    except ValueError as error:
        raise AIInvalidPayloadError(f"{source} is not JSON: {error}") from error
    if not isinstance(data, Mapping):
        raise AIInvalidPayloadError(f"{source} is {type(data).__name__} instead of an object")
    return {str(key): value for key, value in data.items()}


def _safe_json(response: httpx.Response) -> dict[str, object]:
    try:
        data = response.json()
    except ValueError:
        return {}
    if not isinstance(data, Mapping):
        return {}
    return {str(key): value for key, value in data.items()}


def _reported_capabilities(data: Mapping[str, object]) -> tuple[str, ...] | None:
    reported = data.get("capabilities")
    if isinstance(reported, Sequence) and not isinstance(reported, (str, bytes)):
        return tuple(str(item) for item in reported)
    return None


def _error_text(response: httpx.Response) -> str:
    text = response.text.strip()
    if not text:
        return "no detail"
    return text[:200]


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _text(value: object, location: str, *, required: bool = False) -> str:
    if value is None:
        if required:
            raise AIConfigurationError(f"{location} is required")
        return ""
    if not isinstance(value, str) or not value.strip():
        raise AIConfigurationError(f"{location} must be a non-empty string")
    return value


def _optional_text(value: object, location: str) -> str | None:
    if value is None:
        return None
    return _text(value, location)


def _optional_number(value: object, location: str, *, default: float | None) -> float | None:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AIConfigurationError(f"{location} must be a number")
    try:
        return _as_float(value, location)
    except ConfigurationError as error:
        raise AIConfigurationError(str(error)) from error


def _flag(value: object, location: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, (bool, str, int)):
        raise AIConfigurationError(f"{location} must be true or false")
    try:
        return _as_bool(value, location)
    except ConfigurationError as error:
        raise AIConfigurationError(str(error)) from error
