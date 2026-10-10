"""The deterministic fake provider covers every scenario the facade must survive."""

import asyncio
import json

import pytest

from xyberos.ai import (
    ChatRequest,
    EmbeddingRequest,
    FakeModelProvider,
    FinishReason,
    Message,
    ModelCapabilities,
    ModelHealth,
    ModelReply,
    ModelStatus,
    ToolCall,
    ToolSpec,
    Usage,
)
from xyberos.errors import (
    AIRateLimitError,
    AITimeoutError,
    AITransportError,
    AIUnsupportedCapabilityError,
)

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}}


def request() -> ChatRequest:
    return ChatRequest(messages=(Message.user("hi"),))


def test_replies_play_in_order_and_the_last_one_repeats() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.ok("first"), ModelReply.ok("second")])

        assert (await provider.chat(request())).message.content == "first"
        assert (await provider.chat(request())).message.content == "second"
        assert (await provider.chat(request())).message.content == "second"
        assert provider.calls == 3

    asyncio.run(scenario())


def test_a_provider_without_a_script_answers_once() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider()

        response = await provider.chat(request())

        assert response.message.content == "fake reply"
        assert response.finish_reason is FinishReason.STOP
        assert provider.calls == 1

    asyncio.run(scenario())


def test_usage_and_model_identity_are_reported() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(
            [ModelReply.ok("hi", usage=Usage(11, 22), model="scripted-model")]
        )

        response = await provider.chat(request())

        assert response.usage == Usage(input_tokens=11, output_tokens=22)
        assert response.model == "scripted-model"

    asyncio.run(scenario())


def test_tool_call_replies_are_parsed_for_the_facade() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(
            [ModelReply.tools(ToolCall(name="weather", arguments={"city": "Oslo"}))]
        )

        response = await provider.chat(
            request_with_tools := ChatRequest(
                messages=(Message.user("hi"),),
                tools=(ToolSpec(name="weather", parameters={"type": "object"}),),
            )
        )

        assert response.message.tool_calls[0].name == "weather"
        assert dict(response.message.tool_calls[0].arguments) == {"city": "Oslo"}
        assert response.finish_reason is FinishReason.TOOL_CALLS
        assert request_with_tools.tools[0].name == "weather"

    asyncio.run(scenario())


def test_failure_replies_raise_the_scripted_error() -> None:
    async def scenario() -> None:
        with pytest.raises(AIRateLimitError):
            await FakeModelProvider([ModelReply.rate_limited()]).chat(request())
        with pytest.raises(AITransportError):
            await FakeModelProvider([ModelReply.transient()]).chat(request())
        with pytest.raises(AITimeoutError):
            await FakeModelProvider([ModelReply.timeout()]).chat(request())
        with pytest.raises(ValueError, match="custom"):
            await FakeModelProvider([ModelReply.failing(ValueError("custom"))]).chat(request())

    asyncio.run(scenario())


def test_a_failure_reply_can_be_combined_with_a_delay() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.rate_limited(delay=5.0)])

        task = asyncio.ensure_future(provider.chat(request()))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert provider.observed_cancellations == 1

    asyncio.run(scenario())


def test_the_fake_enforces_declared_capabilities_like_a_real_adapter() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(
            [ModelReply.ok("hi")], capabilities=ModelCapabilities(streaming=True)
        )

        with pytest.raises(AIUnsupportedCapabilityError) as structured:
            await provider.chat(ChatRequest(messages=(Message.user("hi"),), response_schema=SCHEMA))
        assert structured.value.capability == "structured_output"

        with pytest.raises(AIUnsupportedCapabilityError) as tools:
            await provider.chat(
                ChatRequest(
                    messages=(Message.user("hi"),),
                    tools=(ToolSpec(name="weather", parameters={"type": "object"}),),
                )
            )
        assert tools.value.capability == "tools"

        with pytest.raises(AIUnsupportedCapabilityError) as embeddings:
            await provider.embed(EmbeddingRequest(inputs=("a",)))
        assert embeddings.value.capability == "embeddings"

    asyncio.run(scenario())


def test_streaming_yields_the_scripted_chunks_and_a_final_marker() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(
            [ModelReply.ok("hello world", chunks=("hello ", "world"), usage=Usage(4, 2))]
        )

        chunks = [chunk async for chunk in provider.stream(request())]

        assert [chunk.content for chunk in chunks] == ["hello ", "world", ""]
        assert [chunk.done for chunk in chunks] == [False, False, True]
        assert chunks[-1].usage == Usage(input_tokens=4, output_tokens=2)
        assert all(chunk.model == "fake-model" for chunk in chunks)

    asyncio.run(scenario())


def test_streaming_a_single_chunk_when_none_are_scripted() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.ok("whole")])

        chunks = [chunk async for chunk in provider.stream(request())]

        assert [chunk.content for chunk in chunks] == ["whole", ""]

    asyncio.run(scenario())


def test_streaming_a_failure_reply_raises() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider([ModelReply.transient()])

        with pytest.raises(AITransportError):
            async for _ in provider.stream(request()):
                pass

    asyncio.run(scenario())


def test_embeddings_are_deterministic_per_input() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider()

        first = await provider.embed(EmbeddingRequest(inputs=("Oslo", "Oslo", "Bergen")))
        second = await provider.embed(EmbeddingRequest(inputs=("Oslo", "Oslo", "Bergen")))

        assert first.embeddings == second.embeddings
        assert first.embeddings[0] == first.embeddings[1]
        assert first.embeddings[0] != first.embeddings[2]
        assert first.dimensions == 4

    asyncio.run(scenario())


def test_an_embedding_failure_can_be_scripted() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider(embed_error=AITransportError("no vectors today"))

        with pytest.raises(AITransportError, match="no vectors today"):
            await provider.embed(EmbeddingRequest(inputs=("a",)))

    asyncio.run(scenario())


def test_health_is_ready_by_default_and_scriptable() -> None:
    async def scenario() -> None:
        assert (await FakeModelProvider().health()).status is ModelStatus.READY

        unavailable = ModelHealth(status=ModelStatus.MODEL_UNAVAILABLE, model="gone")
        assert (await FakeModelProvider(health=unavailable).health()) == unavailable

    asyncio.run(scenario())


def test_requests_are_recorded_and_can_be_reset() -> None:
    async def scenario() -> None:
        provider = FakeModelProvider()

        await provider.chat(request())
        await provider.chat(request())

        assert provider.calls == 2
        assert len(provider.requests) == 2
        assert provider.requests[0].messages[0].content == "hi"

        provider.reset()

        assert provider.calls == 0
        assert provider.requests == []

    asyncio.run(scenario())


def test_prefixed_reply_builders_produce_the_text_the_facade_validates() -> None:
    async def scenario() -> None:
        payload = FakeModelProvider([ModelReply.json_payload({"answer": "yes"})])
        response = await payload.chat(request())

        assert json.loads(response.message.content) == {"answer": "yes"}

        wrong_shape = FakeModelProvider([ModelReply.wrong_shape({"other": 1})])
        assert json.loads((await wrong_shape.chat(request())).message.content) == {"other": 1}

        malformed = FakeModelProvider([ModelReply.malformed(content="not json")])
        assert (await malformed.chat(request())).message.content == "not json"

    asyncio.run(scenario())
