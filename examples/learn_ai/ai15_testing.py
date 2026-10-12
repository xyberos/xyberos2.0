"""Lesson 15 — testing the AI path with no model service.

Run it with:

    python -m learn_ai.ai15_testing
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from xyberos import Retry, StepContext, Workflow, seconds
from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelCapabilities,
    ModelReply,
    Tool,
    ToolCall,
    ToolEvent,
    ToolSet,
    ToolSpec,
)
from xyberos.errors import AIUnsupportedCapabilityError

PROMPT = "How long does a refund take?"
SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {"topic": {"type": "string"}},
    "required": ["topic"],
    "additionalProperties": False,
}


def lookup() -> Tool:
    """A read-only tool, so the test can assert what the model asked for."""

    async def handler(arguments: Mapping[str, object], context: object) -> dict[str, object]:
        return {"topic": arguments["topic"], "note": "three business days"}

    return Tool(
        spec=ToolSpec(name="lookup", description="Look up a topic", parameters=LOOKUP_SCHEMA),
        handler=handler,
    )


async def check_the_prompt_is_what_you_wrote() -> str:
    """The prompt is a contract: assert it, rather than reading it in a log."""
    provider = FakeModelProvider([ModelReply.json_payload({"answer": "Three days."})])
    await AIFacade(provider).structured(
        ChatRequest(
            messages=(Message.system("Answer with the schema."), Message.user(PROMPT)),
            response_schema=SCHEMA,
        )
    )
    sent = provider.requests[0].messages
    assert sent[0].content == "Answer with the schema."
    assert sent[1].content == PROMPT
    return f"the provider received {len(sent)} messages, system first"


async def check_a_transient_failure_is_retried() -> str:
    """A failure the policy calls transient is retried inside the step that made the call."""
    provider = FakeModelProvider([ModelReply.transient(), ModelReply.ok("Second time lucky.")])

    async def ask(value: str, context: StepContext) -> str:
        response = await AIFacade(provider).chat(ChatRequest(messages=(Message.user(value),)))
        return response.message.content

    workflow = Workflow("retry", version="1", input_type=str).step(
        "ask", ask, retry=Retry(max_attempts=2)
    )
    await workflow.run(input=PROMPT, timeout=seconds(5))
    assert provider.calls == 2, provider.calls
    return f"succeeded on attempt 2 with {provider.calls} calls"


async def check_capabilities_are_enforced() -> str:
    """A provider that does not claim structured output is refused before the call."""
    provider = FakeModelProvider(capabilities=ModelCapabilities(structured_output=False))
    try:
        await AIFacade(provider).structured(
            ChatRequest(messages=(Message.user(PROMPT),), response_schema=SCHEMA)
        )
    except AIUnsupportedCapabilityError as error:
        assert provider.calls == 0, "no call should have been made"
        return f"refused before any call: {type(error).__name__}"
    raise AssertionError("the refusal did not happen")


async def check_tool_calls_are_observable() -> str:
    """The event sink is the assertion surface for what the model asked the tools to do."""
    events: list[ToolEvent] = []
    tools = ToolSet.of(lookup(), on_event=events.append)
    provider = FakeModelProvider(
        [
            ModelReply.tools(ToolCall(name="lookup", arguments={"topic": "refunds"})),
            ModelReply.ok("Three business days."),
        ]
    )
    await AIFacade(provider).chat_with_tools(
        ChatRequest(messages=(Message.user(PROMPT),)), tools=tools, max_rounds=2
    )
    kinds = [event.type.value for event in events]
    assert kinds == ["requested", "succeeded"], kinds
    assert events[0].argument_keys == ("topic",)
    return f"events observed: {kinds}"


async def main() -> None:
    """Four checks, no model service, no network, and the same result every time."""
    checks = (
        check_the_prompt_is_what_you_wrote,
        check_a_transient_failure_is_retried,
        check_capabilities_are_enforced,
        check_tool_calls_are_observable,
    )
    for check in checks:
        print("ok -", check.__name__, "-", await check())
    print(f"{len(checks)} checks passed with no model service")


if __name__ == "__main__":
    asyncio.run(main())
