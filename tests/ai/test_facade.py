"""The facade enforces capabilities, budgets, validation, and the logging policy."""

import asyncio
import logging
import time

import pytest

from xyberos.ai import (
    AIFacade,
    ChatChunk,
    ChatRequest,
    ChatResponse,
    EmbeddingRequest,
    EmbeddingResponse,
    FakeModelProvider,
    LoggingPolicy,
    Message,
    ModelCapabilities,
    ModelHealth,
    ModelReply,
    ModelStatus,
    Tool,
    ToolCall,
    ToolSet,
    ToolSpec,
    Usage,
)
from xyberos.errors import (
    AIConfigurationError,
    AIInvalidPayloadError,
    AIRateLimitError,
    AIRefusalError,
    AIRequestError,
    AISchemaError,
    AITimeoutError,
    AIToolError,
    AITransportError,
    AIUnsupportedCapabilityError,
    TransientError,
)
from xyberos.runtime.context import bind_deadline

CITY_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}
WEATHER_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
}


def user_message() -> ChatRequest:
    return ChatRequest(messages=(Message.user("weather in Oslo?"),))


def weather_tool() -> Tool:
    async def handler(arguments, context):
        return {"city": arguments["city"], "celsius": 11}

    return Tool(
        spec=ToolSpec(name="weather", description="look up weather", parameters=WEATHER_SCHEMA),
        handler=handler,
    )


class BlockingProvider:
    """A provider that never answers, so a test controls when a call ends."""

    capabilities = ModelCapabilities(tools=True, structured_output=True)

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancellations = 0

    async def chat(self, request: ChatRequest) -> ChatResponse:
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancellations += 1
            raise
        raise AssertionError("unreachable")

    def stream(self, request: ChatRequest):  # pragma: no cover - not exercised here
        raise NotImplementedError


def test_a_chat_call_returns_the_response_and_its_usage() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.ok("hello", usage=Usage(3, 4))])
        facade = AIFacade(provider)

        response = await facade.chat(user_message())

        assert response.message.content == "hello"
        assert response.usage.total_tokens == 7
        assert response.rounds == 1
        assert provider.calls == 1

    asyncio.run(scenario())


def test_a_structured_call_returns_the_validated_payload() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.json_payload({"city": "Oslo"})])
        facade = AIFacade(provider)
        request = ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA)

        response = await facade.chat(request)

        assert response.structured == {"city": "Oslo"}
        assert response.message.content == '{"city": "Oslo"}'
        assert await facade.structured(request) == {"city": "Oslo"}

    asyncio.run(scenario())


def test_a_structured_call_rejects_a_payload_that_does_not_match_the_schema() -> None:
    async def scenario() -> None:
        facade = AIFacade(FakeModelProvider([ModelReply.wrong_shape({"days": 2})]))

        with pytest.raises(AISchemaError, match=r"the model response at \$ is missing"):
            await facade.structured(
                ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA)
            )

    asyncio.run(scenario())


def test_content_that_is_not_json_is_a_provider_payload_failure() -> None:
    async def scenario() -> None:
        facade = AIFacade(FakeModelProvider([ModelReply.malformed()]))

        with pytest.raises(AIInvalidPayloadError, match="not JSON"):
            await facade.structured(
                ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA)
            )

    asyncio.run(scenario())


def test_structured_output_needs_a_schema() -> None:
    async def scenario() -> None:
        facade = AIFacade(FakeModelProvider())

        with pytest.raises(AIRequestError, match="needs a response_schema"):
            await facade.structured(user_message())

    asyncio.run(scenario())


def test_a_refusal_is_reported_rather_than_returned_as_content() -> None:
    async def scenario() -> None:
        facade = AIFacade(FakeModelProvider([ModelReply.refusal()]))

        with pytest.raises(AIRefusalError, match="refused the request"):
            await facade.chat(user_message())

    asyncio.run(scenario())


def test_failure_classification_drives_retry_policy() -> None:
    assert issubclass(AITransportError, TransientError)
    assert issubclass(AITimeoutError, TransientError)
    assert issubclass(AIRateLimitError, TransientError)
    assert not issubclass(AISchemaError, TransientError)
    assert not issubclass(AIRefusalError, TransientError)
    assert not issubclass(AIRequestError, TransientError)


def test_provider_failures_reach_the_caller_classified_and_unretried() -> None:
    async def scenario() -> None:
        rate_limited = FakeModelProvider([ModelReply.rate_limited()])
        with pytest.raises(AIRateLimitError):
            await AIFacade(rate_limited).chat(user_message())
        assert rate_limited.calls == 1

        transport = FakeModelProvider([ModelReply.transient()])
        with pytest.raises(AITransportError):
            await AIFacade(transport).chat(user_message())

        timed_out = FakeModelProvider([ModelReply.timeout()])
        with pytest.raises(AITimeoutError):
            await AIFacade(timed_out).chat(user_message())

    asyncio.run(scenario())


def test_capabilities_are_enforced_before_a_call_is_made() -> None:
    async def scenario() -> None:
        limited = FakeModelProvider([ModelReply.ok("hi")], capabilities=ModelCapabilities())
        facade = AIFacade(limited)

        with pytest.raises(AIUnsupportedCapabilityError) as caught:
            await facade.chat(
                ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA)
            )
        assert caught.value.capability == "structured_output"

        with pytest.raises(AIUnsupportedCapabilityError) as tools_error:
            await facade.chat(
                ChatRequest(messages=(Message.user("?"),), tools=(weather_tool().spec,))
            )
        assert tools_error.value.capability == "tools"

        assert limited.calls == 0
        assert isinstance(facade.capabilities, ModelCapabilities)

    asyncio.run(scenario())


def test_a_provider_without_the_requested_method_reports_the_missing_capability() -> None:
    async def scenario() -> None:
        class ChatOnly:
            capabilities = ModelCapabilities()

            async def chat(self, request: ChatRequest) -> ChatResponse:
                return ChatResponse(message=Message.assistant("hi"), model="chat-only")

            def stream(self, request: ChatRequest):
                yield ChatChunk(content="hi")

        facade = AIFacade(ChatOnly())

        with pytest.raises(AIUnsupportedCapabilityError) as caught:
            await facade.embed(EmbeddingRequest(inputs=("a",)))
        assert caught.value.capability == "embeddings"

        with pytest.raises(AIUnsupportedCapabilityError) as health_error:
            await facade.health()
        assert health_error.value.capability == "health"

    asyncio.run(scenario())


def test_a_provider_without_capabilities_cannot_be_trusted() -> None:
    async def scenario() -> None:
        class Sloppy:
            async def chat(self, request: ChatRequest) -> ChatResponse:
                return ChatResponse(message=Message.assistant("hi"), model="sloppy")

        facade = AIFacade(Sloppy())

        with pytest.raises(AIUnsupportedCapabilityError) as caught:
            await facade.chat(user_message())
        assert caught.value.capability == "capabilities"

    asyncio.run(scenario())


def test_a_provider_that_implements_nothing_is_rejected_at_construction() -> None:
    with pytest.raises(AIConfigurationError, match="must implement chat"):
        AIFacade(object())
    with pytest.raises(AIConfigurationError, match="needs a provider"):
        AIFacade(None)


def test_a_request_budget_stops_a_slow_call() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.slow(5.0)])
        facade = AIFacade(provider)

        with pytest.raises(AITimeoutError, match="exceeded its budget"):
            await facade.chat(ChatRequest(messages=(Message.user("?"),), timeout=0.01))

        assert provider.observed_cancellations == 1

    asyncio.run(scenario())


def test_an_expired_deadline_stops_the_call_before_the_provider_is_asked() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.ok("hi")])
        facade = AIFacade(provider)

        with (
            bind_deadline(time.monotonic() - 1),
            pytest.raises(AITimeoutError, match="no time left"),
        ):
            await facade.chat(user_message())

        assert provider.calls == 0

    asyncio.run(scenario())


def test_a_bound_deadline_shortens_the_request_budget() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.slow(5.0)])
        facade = AIFacade(provider)

        with bind_deadline(time.monotonic() + 0.01), pytest.raises(AITimeoutError):
            await facade.chat(ChatRequest(messages=(Message.user("?"),), timeout=30))

        assert provider.calls == 1

    asyncio.run(scenario())


def test_cancelling_the_caller_propagates_and_is_observed() -> None:
    async def scenario() -> None:
        provider = BlockingProvider()
        facade = AIFacade(provider)

        task = asyncio.ensure_future(facade.chat(user_message()))
        await provider.started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert provider.cancellations == 1

    asyncio.run(scenario())


def test_logging_records_metadata_without_content_by_default(caplog) -> None:
    async def scenario() -> None:
        facade = AIFacade(
            FakeModelProvider([ModelReply.ok("secret-completion", usage=Usage(2, 5))])
        )

        with caplog.at_level(logging.DEBUG, logger="xyberos.ai"):
            await facade.chat(ChatRequest(messages=(Message.user("secret-prompt"),)))

    asyncio.run(scenario())

    assert "provider=fake" in caplog.text
    assert "input_tokens=2" in caplog.text
    assert "output_tokens=5" in caplog.text
    assert "secret-prompt" not in caplog.text
    assert "secret-completion" not in caplog.text


def test_content_capture_is_opt_in_truncated_and_redacted(caplog) -> None:
    async def scenario() -> None:
        policy = LoggingPolicy.capturing(max_content_length=20, redact=("sk-secret",))
        facade = AIFacade(FakeModelProvider([ModelReply.ok("done")]), logging_policy=policy)

        with caplog.at_level(logging.DEBUG, logger="xyberos.ai"):
            await facade.chat(
                ChatRequest(messages=(Message.user("token sk-secret and a long tail here"),))
            )

    asyncio.run(scenario())

    assert "sk-secret" not in caplog.text
    assert "[redacted]" in caplog.text
    assert "ai prompt role=user" in caplog.text
    assert "..." in caplog.text


def test_the_logging_policy_rejects_an_impossible_truncation_length() -> None:
    with pytest.raises(AIConfigurationError, match="max_content_length"):
        LoggingPolicy(max_content_length=0)


def test_a_tool_loop_runs_tools_and_accumulates_usage() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(
            [
                ModelReply.tools(
                    ToolCall(name="weather", arguments={"city": "Oslo"}), usage=Usage(3, 2)
                ),
                ModelReply.ok("It is 11C.", usage=Usage(9, 4)),
            ]
        )
        facade = AIFacade(provider)
        tools = ToolSet.of(weather_tool())

        response = await facade.chat_with_tools(user_message(), tools=tools)

        assert response.message.content == "It is 11C."
        assert response.rounds == 2
        assert response.usage == Usage(input_tokens=12, output_tokens=6)
        assert provider.requests[0].messages[-1].content == "weather in Oslo?"
        assert provider.requests[1].messages[-1].role.value == "tool"
        assert provider.requests[1].messages[-1].tool_name == "weather"

    asyncio.run(scenario())


def test_a_tool_loop_stops_at_the_configured_round_limit() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(
            [ModelReply.tools(ToolCall(name="weather", arguments={"city": "Oslo"}))]
        )
        facade = AIFacade(provider)

        with pytest.raises(AIToolError, match="after 2 round"):
            await facade.chat_with_tools(
                user_message(), tools=ToolSet.of(weather_tool()), max_rounds=2
            )

    asyncio.run(scenario())


def test_a_tool_loop_needs_the_tool_capability_and_a_valid_limit() -> None:
    async def scenario() -> None:
        limited = AIFacade(
            FakeModelProvider([ModelReply.ok("hi")], capabilities=ModelCapabilities(streaming=True))
        )

        with pytest.raises(AIUnsupportedCapabilityError) as caught:
            await limited.chat_with_tools(user_message(), tools=ToolSet.of(weather_tool()))
        assert caught.value.capability == "tools"

        with pytest.raises(AIRequestError, match="max_rounds must be at least 1"):
            await limited.chat_with_tools(user_message(), tools=ToolSet(), max_rounds=0)

    asyncio.run(scenario())


def test_tools_can_be_invoked_directly_from_a_response() -> None:
    async def scenario() -> None:
        tools = ToolSet.of(weather_tool())
        response = ChatResponse(
            message=Message.assistant(
                tool_calls=(ToolCall(name="weather", arguments={"city": "Oslo"}),)
            ),
            model="fake",
        )

        results = await AIFacade(FakeModelProvider()).invoke_tools(response, tools=tools)

        assert results[0].ok
        assert results[0].value == {"city": "Oslo", "celsius": 11}

    asyncio.run(scenario())


def test_a_response_that_asks_for_tools_is_not_schema_validated() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(
            [
                ModelReply.tools(ToolCall(name="weather", arguments={"city": "Oslo"})),
                ModelReply.json_payload({"city": "Oslo"}),
            ]
        )
        facade = AIFacade(provider)
        request = ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA)

        response = await facade.chat_with_tools(request, tools=ToolSet.of(weather_tool()))

        assert response.structured == {"city": "Oslo"}
        assert response.message.tool_calls == ()

    asyncio.run(scenario())


def test_streaming_yields_content_chunks_and_rejects_what_it_cannot_stream() -> None:
    async def scenario() -> None:
        facade = AIFacade(
            FakeModelProvider([ModelReply.ok("hello world", chunks=("hello ", "world"))])
        )

        chunks = [chunk async for chunk in facade.stream(user_message())]

        assert [chunk.content for chunk in chunks] == ["hello ", "world", ""]
        assert chunks[-1].done

        with pytest.raises(AIRequestError, match="cannot offer tools"):
            facade.stream(ChatRequest(messages=(Message.user("?"),), tools=(weather_tool().spec,)))
        with pytest.raises(AIRequestError, match="cannot ask for a response schema"):
            facade.stream(ChatRequest(messages=(Message.user("?"),), response_schema=CITY_SCHEMA))

    asyncio.run(scenario())


def test_streaming_requires_the_streaming_capability() -> None:
    async def scenario() -> None:
        facade = AIFacade(
            FakeModelProvider(
                [ModelReply.ok("hi")], capabilities=ModelCapabilities(streaming=False)
            )
        )

        with pytest.raises(AIUnsupportedCapabilityError) as caught:
            facade.stream(user_message())
        assert caught.value.capability == "streaming"

    asyncio.run(scenario())


def test_streaming_stops_when_the_budget_runs_out() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.ok("slow", delay=5.0, chunks=("a", "b"))])
        facade = AIFacade(provider)

        with pytest.raises(AITimeoutError, match="stream exceeded its budget"):
            async for _ in facade.stream(ChatRequest(messages=(Message.user("?"),), timeout=0.01)):
                pass

    asyncio.run(scenario())


def test_embeddings_are_returned_and_capability_checked() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider()
        facade = AIFacade(provider)

        response = await facade.embed(EmbeddingRequest(inputs=("a", "bb")))

        assert isinstance(response, EmbeddingResponse)
        assert response.dimensions == 4
        assert response.embeddings[0][0] == 1.0

        limited = AIFacade(
            FakeModelProvider(capabilities=ModelCapabilities(structured_output=True))
        )
        with pytest.raises(AIUnsupportedCapabilityError, match="no embedding model"):
            await limited.embed(EmbeddingRequest(inputs=("a",)))

    asyncio.run(scenario())


def test_the_facade_closes_the_provider_that_owns_resources() -> None:
    async def scenario() -> None:
        closed: list[str] = []

        class OwningProvider(FakeModelProvider):
            async def aclose(self) -> None:
                closed.append("closed")

        await AIFacade(OwningProvider()).aclose()
        await AIFacade(FakeModelProvider()).aclose()

        assert closed == ["closed"]

    asyncio.run(scenario())


def test_health_is_reported_through_the_facade() -> None:
    async def scenario() -> None:
        healthy = AIFacade(FakeModelProvider())
        assert (await healthy.health()).status is ModelStatus.READY

        unhealthy = AIFacade(
            FakeModelProvider(
                health=ModelHealth(status=ModelStatus.MODEL_UNAVAILABLE, model="fake")
            )
        )
        assert (await unhealthy.health()).status is ModelStatus.MODEL_UNAVAILABLE

    asyncio.run(scenario())
