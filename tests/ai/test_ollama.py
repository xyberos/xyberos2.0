"""The Ollama adapter maps the documented API in both directions and never invents a request."""

import asyncio
import json
from collections.abc import Callable

import httpx
import pytest

from xyberos.ai import (
    ChatRequest,
    EmbeddingRequest,
    Message,
    ModelStatus,
    Role,
    ToolCall,
    ToolSpec,
)
from xyberos.ai.ollama import (
    CHAT_PATH,
    EMBED_PATH,
    MINIMUM_SUPPORTED_VERSION,
    SHOW_PATH,
    VERSION_PATH,
    OllamaProvider,
    OllamaSettings,
    _version_is_below,
    ollama_provider,
)
from xyberos.errors import (
    AIConfigurationError,
    AIInvalidPayloadError,
    AIModelNotFoundError,
    AIRateLimitError,
    AIRequestError,
    AITimeoutError,
    AITransportError,
    AIUnsupportedCapabilityError,
)

WEATHER_SPEC = ToolSpec(
    name="weather",
    description="look up weather",
    parameters={"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
)
CITY_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}


class Routes:
    """A scripted set of HTTP routes that records every request it receives."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self.routes.get(request.url.path)
        if route is None:
            return httpx.Response(404, json={"error": "unknown path"})
        if callable(route):
            return route(request)
        assert isinstance(route, httpx.Response)
        return route

    @property
    def payloads(self) -> list[dict[str, object]]:
        return [json.loads(request.content) for request in self.requests if request.content]

    def payload_for(self, path: str) -> dict[str, object]:
        for request in self.requests:
            if request.url.path == path:
                return json.loads(request.content)
        raise AssertionError(f"no request was made to {path}")


def make_provider(routes: Routes, **settings: object) -> OllamaProvider:
    arguments: dict[str, object] = {"model": "llama3.2", "structured_output": True}
    arguments.update(settings)
    client = httpx.AsyncClient(transport=httpx.MockTransport(routes), base_url="http://ollama.test")
    return OllamaProvider(OllamaSettings(**arguments), client=client)  # type: ignore[arg-type]


def chat_route(handler: Callable[[httpx.Request], httpx.Response]) -> Routes:
    return Routes({CHAT_PATH: handler})


def _chat_body(content: str) -> dict[str, object]:
    return {"model": "llama3.2", "message": {"role": "assistant", "content": content}, "done": True}


def test_settings_require_an_explicit_model() -> None:
    with pytest.raises(AIConfigurationError, match="never chooses a model"):
        OllamaSettings(model="")
    with pytest.raises(AIConfigurationError, match="never chooses a model"):
        OllamaSettings(model="   ")


def test_settings_validate_the_base_url_and_never_accept_credentials() -> None:
    assert OllamaSettings(model="m", base_url="http://127.0.0.1:11434/").base_url == (
        "http://127.0.0.1:11434"
    )
    with pytest.raises(AIConfigurationError, match="must be an http"):
        OllamaSettings(model="m", base_url="ollama.test")
    with pytest.raises(AIConfigurationError, match="must not embed credentials"):
        OllamaSettings(model="m", base_url="http://user:pass@127.0.0.1:11434")
    with pytest.raises(AIConfigurationError, match="must be a non-empty URL"):
        OllamaSettings(model="m", base_url="")


def test_settings_validate_timeouts_and_options() -> None:
    with pytest.raises(AIConfigurationError, match="timeout must be greater than zero"):
        OllamaSettings(model="m", timeout=0)
    with pytest.raises(AIConfigurationError, match="connect_timeout must be greater than zero"):
        OllamaSettings(model="m", connect_timeout=-1)
    with pytest.raises(AIConfigurationError, match="embedding_model must be a non-empty"):
        OllamaSettings(model="m", embedding_model=" ")
    with pytest.raises(AIConfigurationError, match="reserved key"):
        OllamaSettings(model="m", options={"model": "another-model"})
    with pytest.raises(AIConfigurationError, match="must be non-empty strings"):
        OllamaSettings(model="m", options={"": 1})
    with pytest.raises(AIConfigurationError, match="must be JSON-serializable"):
        OllamaSettings(model="m", options={"callback": object()})
    with pytest.raises(AIConfigurationError, match="options must be a table/object"):
        OllamaSettings(model="m", options=["num_ctx"])  # type: ignore[arg-type]


def test_settings_validate_the_minimum_version() -> None:
    assert OllamaSettings(model="m").minimum_version == MINIMUM_SUPPORTED_VERSION
    assert OllamaSettings(model="m", minimum_version="0.4.7").minimum_version == "0.4.7"
    with pytest.raises(AIConfigurationError, match="non-empty version"):
        OllamaSettings(model="m", minimum_version="  ")
    with pytest.raises(AIConfigurationError, match="dotted numeric version"):
        OllamaSettings(model="m", minimum_version="latest")


def test_the_minimum_version_comes_from_configuration() -> None:
    settings = OllamaSettings.from_mapping({"model": "m", "minimum_version": "0.4.7"})

    assert settings.minimum_version == "0.4.7"


def test_settings_declare_capabilities_conservatively() -> None:
    conservative = OllamaSettings(model="m")

    assert not conservative.capabilities.tools
    assert not conservative.capabilities.structured_output
    assert not conservative.capabilities.embeddings
    assert conservative.capabilities.streaming

    declared = OllamaSettings(
        model="m", tools=True, structured_output=True, embedding_model="nomic-embed-text"
    )
    assert declared.capabilities == declared.capabilities.__class__(
        tools=True, structured_output=True, streaming=True, embeddings=True
    )


def test_settings_can_be_built_from_a_configuration_section() -> None:
    settings = OllamaSettings.from_mapping(
        {
            "model": "llama3.2",
            "base_url": "http://localhost:11434/",
            "embedding_model": "nomic-embed-text",
            "timeout": "30",
            "connect_timeout": 2,
            "tools": "true",
            "structured_output": True,
            "streaming": False,
            "options": {"num_ctx": 2048},
        }
    )

    assert settings.model == "llama3.2"
    assert settings.base_url == "http://localhost:11434"
    assert settings.timeout == 30.0
    assert settings.connect_timeout == 2.0
    assert settings.tools is True
    assert settings.streaming is False
    assert dict(settings.options) == {"num_ctx": 2048}

    with pytest.raises(AIConfigurationError, match="model is required"):
        OllamaSettings.from_mapping({"timeout": 10})
    with pytest.raises(AIConfigurationError, match="unknown setting"):
        OllamaSettings.from_mapping({"model": "m", "temperature": 0.5})
    with pytest.raises(AIConfigurationError, match="must be true or false"):
        OllamaSettings.from_mapping({"model": "m", "tools": [1]})
    with pytest.raises(AIConfigurationError, match="options must be a table/object"):
        OllamaSettings.from_mapping({"model": "m", "options": ["num_ctx"]})
    with pytest.raises(AIConfigurationError, match="must be a table/object"):
        OllamaSettings.from_mapping("model=llama3.2")  # type: ignore[arg-type]


def test_the_adapter_reports_its_identity_and_requires_settings() -> None:
    provider = make_provider(Routes({}), embedding_model="nomic-embed-text")

    assert provider.name == "ollama"
    assert provider.model == "llama3.2"
    assert provider.settings.model == "llama3.2"
    assert provider.capabilities.embeddings
    with pytest.raises(AIConfigurationError, match="expected OllamaSettings"):
        OllamaProvider("not settings")  # type: ignore[arg-type]


def test_a_chat_request_is_mapped_to_the_documented_payload() -> None:
    async def scenario() -> None:
        routes = chat_route(
            lambda request: httpx.Response(
                200, json={"model": "llama3.2", "message": {"role": "assistant", "content": "ok"}}
            )
        )
        provider = make_provider(
            routes, options={"num_ctx": 4096}, tools=True, embedding_model="nomic-embed-text"
        )

        await provider.chat(
            ChatRequest(
                messages=(Message.system("be brief"), Message.user("weather?")),
                temperature=0.2,
                max_tokens=64,
                stop=("END",),
                response_schema=CITY_SCHEMA,
                tools=(WEATHER_SPEC,),
            )
        )

        payload = routes.payload_for(CHAT_PATH)
        assert payload["model"] == "llama3.2"
        assert payload["stream"] is False
        assert payload["format"] == CITY_SCHEMA
        assert payload["options"] == {
            "num_ctx": 4096,
            "temperature": 0.2,
            "num_predict": 64,
            "stop": ["END"],
        }
        assert payload["tools"] == [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "look up weather",
                    "parameters": WEATHER_SPEC.parameters,
                },
            }
        ]
        assert payload["messages"] == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "weather?"},
        ]

    asyncio.run(scenario())


def test_an_assistant_tool_call_is_mapped_back_into_the_conversation() -> None:
    async def scenario() -> None:
        routes = chat_route(lambda request: httpx.Response(200, json={"message": {}}))
        provider = make_provider(routes)

        await provider.chat(
            ChatRequest(
                messages=(
                    Message.assistant(
                        "", tool_calls=(ToolCall(name="weather", arguments={"city": "Oslo"}),)
                    ),
                    Message.tool_result("weather", '{"celsius": 11}'),
                )
            )
        )

        messages = routes.payload_for(CHAT_PATH)["messages"]
        assert messages[0]["tool_calls"] == [
            {"function": {"name": "weather", "arguments": {"city": "Oslo"}}}
        ]
        assert messages[1] == {"role": "tool", "content": '{"celsius": 11}'}

    asyncio.run(scenario())


def test_a_chat_response_is_mapped_into_the_contract() -> None:
    async def scenario() -> None:
        routes = chat_route(
            lambda request: httpx.Response(
                200,
                json={
                    "model": "llama3.2",
                    "message": {
                        "role": "assistant",
                        "content": "It is 11C.",
                        "tool_calls": [
                            {"function": {"name": "weather", "arguments": {"city": "Oslo"}}}
                        ],
                    },
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 12,
                    "eval_count": 7,
                },
            )
        )

        response = await make_provider(routes).chat(ChatRequest(messages=(Message.user("?"),)))

        assert response.message.content == "It is 11C."
        assert response.model == "llama3.2"
        assert response.usage.input_tokens == 12
        assert response.usage.output_tokens == 7
        assert response.message.tool_calls[0].name == "weather"
        assert dict(response.message.tool_calls[0].arguments) == {"city": "Oslo"}
        assert response.finish_reason is not None
        assert response.finish_reason.value == "tool_calls"

    asyncio.run(scenario())


def test_tool_arguments_delivered_as_a_json_string_are_parsed() -> None:
    async def scenario() -> None:
        routes = chat_route(
            lambda request: httpx.Response(
                200,
                json={
                    "message": {
                        "content": "",
                        "tool_calls": [
                            {"function": {"name": "weather", "arguments": '{"city": "Oslo"}'}}
                        ],
                    },
                    "done_reason": "stop",
                },
            )
        )

        response = await make_provider(routes).chat(ChatRequest(messages=(Message.user("?"),)))

        assert dict(response.message.tool_calls[0].arguments) == {"city": "Oslo"}

    asyncio.run(scenario())


def test_finish_reasons_and_model_fallbacks_are_normalized() -> None:
    async def scenario() -> None:
        def route(reason: str) -> Routes:
            return chat_route(
                lambda request: httpx.Response(
                    200, json={"message": {"content": "x"}, "done_reason": reason}
                )
            )

        stopped = await make_provider(route("stop")).chat(
            ChatRequest(messages=(Message.user("?"),))
        )
        limited = await make_provider(route("length")).chat(
            ChatRequest(messages=(Message.user("?"),))
        )
        other = await make_provider(route("unload")).chat(
            ChatRequest(messages=(Message.user("?"),))
        )

        assert stopped.finish_reason is not None and stopped.finish_reason.value == "stop"
        assert limited.finish_reason is not None and limited.finish_reason.value == "length"
        assert other.finish_reason is not None and other.finish_reason.value == "other"
        assert stopped.model == "llama3.2"

    asyncio.run(scenario())


def test_a_response_that_is_not_the_documented_shape_is_rejected() -> None:
    async def scenario() -> None:
        payloads = [
            {"done": True},
            {"message": {"content": 5}},
            {"message": {"content": "", "tool_calls": "nope"}},
            {"message": {"content": "", "tool_calls": [{"not_function": {}}]}},
            {"message": {"content": "", "tool_calls": [{"function": {"name": ""}}]}},
            {
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "w", "arguments": 5}}],
                }
            },
            {
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "w", "arguments": "no"}}],
                }
            },
        ]

        for payload in payloads:
            routes = chat_route(lambda request, body=payload: httpx.Response(200, json=body))
            provider = make_provider(routes, tools=True)
            with pytest.raises(AIInvalidPayloadError):
                await provider.chat(
                    ChatRequest(messages=(Message.user("?"),), tools=(WEATHER_SPEC,))
                )

    asyncio.run(scenario())


def test_a_body_that_is_not_json_is_a_payload_failure() -> None:
    async def scenario() -> None:
        routes = chat_route(lambda request: httpx.Response(200, text="<html>gateway</html>"))

        with pytest.raises(AIInvalidPayloadError, match="not JSON"):
            await make_provider(routes).chat(ChatRequest(messages=(Message.user("?"),)))

    asyncio.run(scenario())


def test_streaming_maps_each_line_into_a_chunk() -> None:
    async def scenario() -> None:
        body = (
            '{"model":"llama3.2","message":{"content":"Hel"},"done":false}\n'
            "\n"
            '{"model":"llama3.2","message":{"content":"lo"},"done":false}\n'
            '{"model":"llama3.2","message":{"content":""},"done":true,'
            '"done_reason":"stop","prompt_eval_count":4,"eval_count":2}\n'
        )
        routes = chat_route(lambda request: httpx.Response(200, text=body))
        provider = make_provider(routes)

        chunks = [
            chunk async for chunk in provider.stream(ChatRequest(messages=(Message.user("?"),)))
        ]

        assert [chunk.content for chunk in chunks] == ["Hel", "lo", ""]
        assert [chunk.done for chunk in chunks] == [False, False, True]
        assert chunks[-1].usage is not None
        assert chunks[-1].usage.input_tokens == 4
        assert routes.payload_for(CHAT_PATH)["stream"] is True

    asyncio.run(scenario())


def test_streaming_rejects_tools_and_schemas_and_checks_capabilities() -> None:
    async def scenario() -> None:
        routes = chat_route(lambda request: httpx.Response(200, text=""))
        provider = make_provider(routes, tools=True)

        with pytest.raises(AIRequestError, match="cannot offer tools"):
            provider.stream(ChatRequest(messages=(Message.user("?"),), tools=(WEATHER_SPEC,)))
        with pytest.raises(AIRequestError, match="cannot ask for a response schema"):
            provider.stream(ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA))

        unstreamed = make_provider(routes, streaming=False)
        with pytest.raises(AIUnsupportedCapabilityError) as caught:
            unstreamed.stream(ChatRequest(messages=(Message.user("?"),)))
        assert caught.value.capability == "streaming"

    asyncio.run(scenario())


def test_streaming_classifies_a_provider_error_line() -> None:
    async def scenario() -> None:
        routes = chat_route(
            lambda request: httpx.Response(200, text='{"error":"model is loading, try again"}\n')
        )

        with pytest.raises(AITransportError, match="temporarily unavailable"):
            async for _ in make_provider(routes).stream(ChatRequest(messages=(Message.user("?"),))):
                pass

    asyncio.run(scenario())


def test_declared_capabilities_are_enforced_before_any_http_call() -> None:
    async def scenario() -> None:
        routes = chat_route(lambda request: httpx.Response(200, json={"message": {}}))
        provider = make_provider(routes, structured_output=False, tools=False)

        with pytest.raises(AIUnsupportedCapabilityError) as structured:
            await provider.chat(
                ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA)
            )
        assert structured.value.capability == "structured_output"
        assert "structured_output = true" in str(structured.value)

        with pytest.raises(AIUnsupportedCapabilityError) as tools:
            await provider.chat(ChatRequest(messages=(Message.user("?"),), tools=(WEATHER_SPEC,)))
        assert tools.value.capability == "tools"

        assert routes.requests == []

    asyncio.run(scenario())


def test_embeddings_use_the_configured_embedding_model() -> None:
    async def scenario() -> None:
        routes = Routes(
            {
                EMBED_PATH: httpx.Response(
                    200,
                    json={
                        "model": "nomic-embed-text",
                        "embeddings": [[0.5, 1.0], [0.25, 2.0]],
                        "prompt_eval_count": 3,
                    },
                )
            }
        )
        provider = make_provider(routes, embedding_model="nomic-embed-text")

        response = await provider.embed(EmbeddingRequest(inputs=("a", "bb")))

        assert response.model == "nomic-embed-text"
        assert response.embeddings == ((0.5, 1.0), (0.25, 2.0))
        assert response.dimensions == 2
        assert response.usage.input_tokens == 3
        assert routes.payload_for(EMBED_PATH) == {
            "model": "nomic-embed-text",
            "input": ["a", "bb"],
        }

    asyncio.run(scenario())


def test_embeddings_need_a_model_and_a_well_formed_answer() -> None:
    async def scenario() -> None:
        no_model = make_provider(Routes({}))
        with pytest.raises(AIConfigurationError, match="no embedding model is configured"):
            await no_model.embed(EmbeddingRequest(inputs=("a",)))

        for payload in (
            {"embeddings": []},
            {"embeddings": "nope"},
            {"embeddings": [[0.5]]},
            {"embeddings": [["a"]]},
        ):
            routes = Routes({EMBED_PATH: httpx.Response(200, json=payload)})
            provider = make_provider(routes, embedding_model="nomic-embed-text")
            with pytest.raises(AIInvalidPayloadError):
                await provider.embed(EmbeddingRequest(inputs=("a", "bb")))

    asyncio.run(scenario())


def test_health_refuses_a_service_below_the_supported_floor() -> None:
    """The floor is only real if it is enforced, so it is enforced where the version is known."""

    async def scenario() -> None:
        old = make_provider(
            Routes({VERSION_PATH: httpx.Response(200, json={"version": "0.4.7"})}),
            embedding_model="nomic-embed-text",
        )
        health = await old.health()

        assert health.status is ModelStatus.UNHEALTHY
        assert health.provider_version == "0.4.7"
        assert "older than the supported minimum 0.5.0" in health.detail
        assert "structured output" in health.detail

        # A later request is refused with the same reason rather than failing inside Ollama...
        with pytest.raises(AIConfigurationError, match="older than the supported minimum"):
            await old.chat(ChatRequest(messages=(Message.user("hi"),)))
        with pytest.raises(AIConfigurationError, match="older than the supported minimum"):
            await old.embed(EmbeddingRequest(inputs=("a",)))
        # ...but only once the version is known, so an unprobed service is never refused.
        unprobed = make_provider(Routes({CHAT_PATH: httpx.Response(200, json=_chat_body("fine"))}))
        answer = await unprobed.chat(ChatRequest(messages=(Message.user("hi"),)))
        assert answer.message.content == "fine"

        # An operator can lower the floor deliberately.
        lowered = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "0.4.7"}),
                    SHOW_PATH: httpx.Response(200, json={"capabilities": ["completion"]}),
                    CHAT_PATH: httpx.Response(200, json=_chat_body("older but working")),
                }
            ),
            minimum_version="0.4.0",
        )
        assert (await lowered.health()).status is ModelStatus.READY
        older = await lowered.chat(ChatRequest(messages=(Message.user("hi"),)))
        assert older.message.content == "older but working"

    asyncio.run(scenario())


def test_a_version_that_cannot_be_compared_is_not_treated_as_too_old() -> None:
    """A version that cannot be measured must not be treated as too old.

    Refusing to work against a service you cannot measure would be worse than the risk it guards.
    """

    async def scenario() -> None:
        development = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "0.5.9-rc2"}),
                    SHOW_PATH: httpx.Response(200, json={"capabilities": ["completion"]}),
                    CHAT_PATH: httpx.Response(200, json=_chat_body("prerelease")),
                }
            )
        )

        assert (await development.health()).status is ModelStatus.READY
        prerelease = await development.chat(ChatRequest(messages=(Message.user("hi"),)))
        assert prerelease.message.content == "prerelease"

        odd = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "dev"}),
                    SHOW_PATH: httpx.Response(200, json={"capabilities": ["completion"]}),
                }
            )
        )
        assert (await odd.health()).status is ModelStatus.READY
        assert not _version_is_below("dev", MINIMUM_SUPPORTED_VERSION)
        assert _version_is_below("0.5.0", "0.5.0") is False
        assert _version_is_below("0.4.9", "0.5.0") is True
        assert _version_is_below("0.10.0", "0.5.0") is False

    asyncio.run(scenario())


def test_health_distinguishes_ready_unreachable_and_unavailable() -> None:
    async def scenario() -> None:
        ready = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "0.5.7"}),
                    SHOW_PATH: httpx.Response(200, json={"capabilities": ["completion", "tools"]}),
                }
            ),
            tools=True,
        )
        healthy = await ready.health()
        assert healthy.status is ModelStatus.READY
        assert healthy.provider_version == "0.5.7"

        unreachable = make_provider(
            Routes(
                {VERSION_PATH: lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused"))}
            )
        )
        offline = await unreachable.health()
        assert offline.status is ModelStatus.UNREACHABLE
        assert "did not answer" in offline.detail

        missing = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "0.5.7"}),
                    SHOW_PATH: httpx.Response(404, json={"error": "model 'llama3.2' not found"}),
                }
            )
        )
        unavailable = await missing.health()
        assert unavailable.status is ModelStatus.MODEL_UNAVAILABLE
        assert "never pulls models" in unavailable.detail

    asyncio.run(scenario())


def test_health_reports_a_capability_mismatch_and_an_unreadable_service() -> None:
    async def scenario() -> None:
        mismatched = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "0.5.7"}),
                    SHOW_PATH: httpx.Response(200, json={"capabilities": ["completion"]}),
                }
            ),
            tools=True,
        )
        health = await mismatched.health()

        assert health.status is ModelStatus.UNHEALTHY
        assert "tools = true" in health.detail

        unreadable = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "0.5.7"}),
                    SHOW_PATH: lambda request: (_ for _ in ()).throw(httpx.ConnectError("gone")),
                }
            )
        )
        assert (await unreadable.health()).status is ModelStatus.UNHEALTHY

        no_capability_field = make_provider(
            Routes(
                {
                    VERSION_PATH: httpx.Response(200, json={"version": "0.5.7"}),
                    SHOW_PATH: httpx.Response(200, json={"details": {"parameter_size": "3B"}}),
                }
            ),
            tools=True,
        )
        assert (await no_capability_field.health()).status is ModelStatus.READY

    asyncio.run(scenario())


def test_http_failures_are_classified_for_retry_policy() -> None:
    async def scenario() -> None:
        cases: list[
            tuple[httpx.Response | Callable[[httpx.Request], httpx.Response], type[Exception]]
        ] = [
            (httpx.Response(429, text="too many requests"), AIRateLimitError),
            (
                httpx.Response(404, json={"error": "model 'llama3.2' not found"}),
                AIModelNotFoundError,
            ),
            (httpx.Response(404, text="cannot POST /api/chat"), AIRequestError),
            (httpx.Response(500, text="boom"), AITransportError),
            (httpx.Response(400, text="bad request"), AIRequestError),
            (
                lambda request: (_ for _ in ()).throw(httpx.ConnectError("refused")),
                AITransportError,
            ),
            (lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), AITimeoutError),
        ]

        for route, expected in cases:
            routes = chat_route(route)
            with pytest.raises(expected):
                await make_provider(routes).chat(ChatRequest(messages=(Message.user("?"),)))

    asyncio.run(scenario())


def test_an_error_field_inside_a_success_response_is_classified() -> None:
    async def scenario() -> None:
        cases = [
            ("model 'llama3.2' not found, try pulling it first", AIModelNotFoundError),
            ("rate limit exceeded", AIRateLimitError),
            ("model is loading, try again", AITransportError),
            ("something nobody recognises", AIRequestError),
        ]

        for message, expected in cases:
            routes = chat_route(
                lambda request, text=message: httpx.Response(200, json={"error": text})
            )
            with pytest.raises(expected):
                await make_provider(routes).chat(ChatRequest(messages=(Message.user("?"),)))

    asyncio.run(scenario())


def test_closing_releases_only_a_client_the_adapter_owns() -> None:
    async def scenario() -> None:
        injected = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200)), base_url="http://x"
        )
        provider = OllamaProvider(OllamaSettings(model="m"), client=injected)

        await provider.aclose()
        assert not injected.is_closed

        owned = make_provider(Routes({}))
        await owned.aclose()
        await owned.aclose()

    asyncio.run(scenario())


def test_the_factory_returns_a_dependency_injection_ready_callable() -> None:
    async def scenario() -> None:
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(200)), base_url="http://x"
        )
        factory = ollama_provider(OllamaSettings(model="llama3.2"), client=client)

        provider = await factory()

        assert isinstance(provider, OllamaProvider)
        assert provider.model == "llama3.2"

    asyncio.run(scenario())


def test_the_adapter_strips_a_trailing_slash_before_building_paths() -> None:
    async def scenario() -> None:
        routes = chat_route(
            lambda request: httpx.Response(200, json={"message": {"content": "ok"}})
        )
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(routes), base_url="http://ollama.test/"
        )
        provider = OllamaProvider(
            OllamaSettings(model="m", base_url="http://ollama.test/"), client=client
        )

        await provider.chat(ChatRequest(messages=(Message.user("?"),)))

        assert routes.requests[0].url.path == CHAT_PATH

    asyncio.run(scenario())


def test_a_tool_message_carries_its_role_and_content_on_the_wire() -> None:
    async def scenario() -> None:
        routes = chat_route(lambda request: httpx.Response(200, json={"message": {}}))

        await make_provider(routes).chat(
            ChatRequest(messages=(Message.tool_result("weather", "{}"),))
        )

        messages = routes.payload_for(CHAT_PATH)["messages"]
        assert messages == [{"role": Role.TOOL.value, "content": "{}"}]

    asyncio.run(scenario())
