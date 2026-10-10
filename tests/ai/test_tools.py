"""Tools are explicitly allowlisted, validated, audited, and never handed a service container."""

import asyncio
import json
import time

import pytest

from xyberos.ai import (
    Tool,
    ToolCall,
    ToolContext,
    ToolEvent,
    ToolEventType,
    ToolResult,
    ToolSet,
    ToolSpec,
)
from xyberos.errors import AITimeoutError, AIToolError
from xyberos.runtime.context import bind_correlation_id, bind_deadline

WEATHER_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}


def weather_tool(handler=None) -> Tool:
    async def default_handler(arguments, context):
        return {"city": arguments["city"], "celsius": 11}

    return Tool(
        spec=ToolSpec(name="weather", description="look up weather", parameters=WEATHER_SCHEMA),
        handler=handler or default_handler,
    )


def test_a_tool_needs_a_callable_handler() -> None:
    with pytest.raises(AIToolError, match="needs a callable handler"):
        Tool(spec=ToolSpec(name="weather"), handler="not callable")  # type: ignore[arg-type]


def test_a_tool_set_is_the_allowlist_and_rejects_duplicates() -> None:
    tools = ToolSet.of(weather_tool())

    assert tools.names == ("weather",)
    assert "weather" in tools
    assert tools.get("shell") is None
    assert [spec.name for spec in tools.specs] == ["weather"]
    with pytest.raises(AIToolError, match="already registered"):
        tools.add(weather_tool())


def test_an_allowed_tool_runs_and_returns_its_value() -> None:
    async def scenario() -> None:
        tools = ToolSet.of(weather_tool())

        result = await tools.invoke(ToolCall(name="weather", arguments={"city": "Oslo"}))

        assert result.ok
        assert result.value == {"city": "Oslo", "celsius": 11}
        assert json.loads(result.render()) == {"celsius": 11, "city": "Oslo"}

    asyncio.run(scenario())


def test_a_tool_outside_the_allowlist_raises_rather_than_running() -> None:
    async def scenario() -> None:
        ran: list[str] = []

        async def handler(arguments, context):
            ran.append("ran")
            return None

        tools = ToolSet.of(weather_tool(handler))

        with pytest.raises(AIToolError) as caught:
            await tools.invoke(ToolCall(name="shell", arguments={"command": "rm -rf /"}))

        assert caught.value.tool == "shell"
        assert "allowed tools: weather" in str(caught.value)
        assert ran == []

    asyncio.run(scenario())


def test_invalid_arguments_come_back_as_a_result_so_a_model_can_correct_itself() -> None:
    async def scenario() -> None:
        ran: list[str] = []

        async def handler(arguments, context):
            ran.append("ran")
            return None

        tools = ToolSet.of(weather_tool(handler))

        result = await tools.invoke(ToolCall(name="weather", arguments={"city": 5}))

        assert not result.ok
        assert result.error_type == "AISchemaError"
        assert "at $.city must be string, got integer" in (result.error or "")
        assert ran == []
        assert json.loads(result.render())["error_type"] == "AISchemaError"

    asyncio.run(scenario())


def test_a_failing_handler_becomes_a_result_and_never_swallows_cancellation() -> None:
    async def scenario() -> None:
        async def explode(arguments, context):
            raise ValueError("the upstream lookup failed")

        tools = ToolSet.of(weather_tool(explode))

        result = await tools.invoke(ToolCall(name="weather", arguments={"city": "Oslo"}))

        assert not result.ok
        assert result.error_type == "ValueError"
        assert result.error == "the upstream lookup failed"

        async def cancel(arguments, context):
            raise asyncio.CancelledError

        cancelling = ToolSet.of(weather_tool(cancel))
        with pytest.raises(asyncio.CancelledError):
            await cancelling.invoke(ToolCall(name="weather", arguments={"city": "Oslo"}))

    asyncio.run(scenario())


def test_tool_events_audit_outcomes_without_recording_argument_values() -> None:
    async def scenario() -> None:
        events: list[ToolEvent] = []
        tools = ToolSet.of(weather_tool(), on_event=events.append)

        await tools.invoke(ToolCall(name="weather", arguments={"city": "Oslo-secret-token"}))

        assert [event.type for event in events] == [
            ToolEventType.REQUESTED,
            ToolEventType.SUCCEEDED,
        ]
        assert [event.sequence for event in events] == [1, 2]
        rendered = "\n".join(event.render() for event in events)
        assert "arguments=city" in rendered
        assert "Oslo-secret-token" not in rendered

        events.clear()
        await tools.invoke(ToolCall(name="weather", arguments={"city": 5}))
        assert [event.type for event in events] == [
            ToolEventType.REQUESTED,
            ToolEventType.INVALID,
        ]
        assert events[1].error_type == "AISchemaError"

        events.clear()
        with pytest.raises(AIToolError):
            await tools.invoke(ToolCall(name="shell", arguments={}))
        assert [event.type for event in events] == [ToolEventType.REQUESTED, ToolEventType.DENIED]

    asyncio.run(scenario())


def test_a_failed_handler_is_audited_without_its_message() -> None:
    async def scenario() -> None:
        async def explode(arguments, context):
            raise ValueError("secret-token in the message")

        events: list[ToolEvent] = []
        tools = ToolSet.of(weather_tool(explode), on_event=events.append)

        await tools.invoke(ToolCall(name="weather", arguments={"city": "Oslo"}))

        assert events[-1].type is ToolEventType.FAILED
        assert events[-1].error_type == "ValueError"
        assert "secret-token" not in events[-1].render()

    asyncio.run(scenario())


def test_events_carry_the_correlation_id_of_the_caller() -> None:
    async def scenario() -> None:
        events: list[ToolEvent] = []
        tools = ToolSet.of(weather_tool(), on_event=events.append)

        with bind_correlation_id("corr-tools"):
            await tools.invoke(ToolCall(name="weather", arguments={"city": "Oslo"}))

        assert {event.correlation_id for event in events} == {"corr-tools"}

    asyncio.run(scenario())


def test_a_handler_receives_immutable_arguments_and_the_context_only() -> None:
    async def scenario() -> None:
        seen: dict[str, object] = {}

        async def handler(arguments, context):
            seen["type"] = type(arguments).__name__
            seen["context"] = context
            with pytest.raises(TypeError):
                arguments["city"] = "mutated"  # type: ignore[index]
            return "ok"

        tools = ToolSet.of(weather_tool(handler))

        with bind_correlation_id("corr-1"):
            await tools.invoke(
                ToolCall(name="weather", arguments={"city": "Oslo"}, call_id="call-7")
            )

        assert seen["type"] == "mappingproxy"
        context = seen["context"]
        assert isinstance(context, ToolContext)
        assert context.call_id == "call-7"
        assert context.correlation_id == "corr-1"
        assert context.deadline is None
        assert {field for field in ToolContext.__dataclass_fields__} == {
            "call_id",
            "deadline",
            "correlation_id",
        }

    asyncio.run(scenario())


def test_a_handler_sees_the_deadline_bound_to_the_context() -> None:
    async def scenario() -> None:
        seen: dict[str, object] = {}

        async def handler(arguments, context):
            seen["remaining"] = context.remaining()
            seen["expired"] = context.expired()
            context.check()
            return "ok"

        tools = ToolSet.of(weather_tool(handler))

        with bind_deadline(time.monotonic() + 30):
            await tools.invoke(ToolCall(name="weather", arguments={"city": "Oslo"}))

        assert 25 < float(seen["remaining"]) <= 30  # type: ignore[arg-type]
        assert seen["expired"] is False

    asyncio.run(scenario())


def test_an_expired_tool_context_reports_a_timeout() -> None:
    context = ToolContext(deadline=time.monotonic() - 1)

    assert context.expired()
    with pytest.raises(AITimeoutError, match="ran out of time"):
        context.check()


def test_several_calls_run_in_order() -> None:
    async def scenario() -> None:
        order: list[str] = []

        async def handler(arguments, context):
            order.append(str(arguments["city"]))
            return "ok"

        tools = ToolSet.of(weather_tool(handler))

        results = await tools.invoke_all(
            (
                ToolCall(name="weather", arguments={"city": "Oslo"}),
                ToolCall(name="weather", arguments={"city": "Bergen"}),
            )
        )

        assert order == ["Oslo", "Bergen"]
        assert [result.ok for result in results] == [True, True]

    asyncio.run(scenario())


def test_a_tool_result_renders_as_json_text() -> None:
    assert ToolResult(tool="t", ok=True, value={"a": 1}).render() == '{"a": 1}'
    assert json.loads(ToolResult(tool="t", ok=False, error_type="X", error="boom").render()) == {
        "error": "boom",
        "error_type": "X",
    }


def test_adding_something_that_is_not_a_tool_is_rejected() -> None:
    tools = ToolSet()

    with pytest.raises(AIToolError, match="expected a Tool"):
        tools.add("weather")  # type: ignore[arg-type]
