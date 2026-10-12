"""Lesson 11 — tools: an allowlist, and arguments checked against a schema.

Run it with:

    python -m learn_ai.ai11_tools
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelReply,
    Tool,
    ToolCall,
    ToolEvent,
    ToolSet,
    ToolSpec,
)
from xyberos.errors import AIToolError

TICKETS = {"T-100": "printer is on fire", "T-101": "badge reader is broken"}

LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {"ticket": {"type": "string"}},
    "required": ["ticket"],
    "additionalProperties": False,
}

COUNT_SCHEMA = {
    "type": "object",
    "properties": {"state": {"type": "string", "enum": ["open", "closed"]}},
    "required": ["state"],
    "additionalProperties": False,
}


def lookup_ticket() -> Tool:
    """A read-only tool: it looks a ticket up and can change nothing."""

    async def handler(arguments: Mapping[str, object], context: object) -> dict[str, object]:
        ticket = str(arguments["ticket"])
        return {"ticket": ticket, "title": TICKETS.get(ticket, "no such ticket")}

    return Tool(
        spec=ToolSpec(
            name="lookup_ticket",
            description="Look up one ticket's title by id",
            parameters=LOOKUP_SCHEMA,
        ),
        handler=handler,
    )


def count_tickets() -> Tool:
    """A second read-only tool, with an argument restricted to an enum."""

    async def handler(arguments: Mapping[str, object], context: object) -> dict[str, object]:
        return {"state": arguments["state"], "count": len(TICKETS)}

    return Tool(
        spec=ToolSpec(
            name="count_tickets",
            description="Count tickets in one state",
            parameters=COUNT_SCHEMA,
        ),
        handler=handler,
    )


def watch(events: list[ToolEvent]) -> object:
    """Return the sink that records what the tool layer did."""

    def sink(event: ToolEvent) -> None:
        events.append(event)

    return sink


async def main() -> None:
    """One tool call the loop performs, one call the allowlist refuses, one round limit."""
    events: list[ToolEvent] = []
    tools = ToolSet.of(lookup_ticket(), count_tickets(), on_event=watch(events))  # type: ignore[arg-type]
    print("allowed:", tools.names)
    print("declared:", [spec.name for spec in tools.specs])

    provider = FakeModelProvider(
        [
            ModelReply.tools(ToolCall(name="lookup_ticket", arguments={"ticket": "T-100"})),
            ModelReply.ok("Ticket T-100 is 'printer is on fire'."),
        ]
    )
    response = await AIFacade(provider).chat_with_tools(
        ChatRequest(messages=(Message.user("What is ticket T-100 about?"),)),
        tools=tools,
        max_rounds=3,
    )
    print("answer:  ", response.message.content, f"(rounds: {response.rounds})")
    for event in events:
        print("  event:", event.type.value, event.tool, event.argument_keys)

    try:
        await tools.invoke(ToolCall(name="refund_customer", arguments={"order": "O-9"}))
    except AIToolError as error:
        print("not allowed:", error)

    bad_arguments = await tools.invoke(ToolCall(name="lookup_ticket", arguments={"id": "T-100"}))
    print("bad args:   ", bad_arguments.ok, bad_arguments.error_type, bad_arguments.error)

    looping = FakeModelProvider(
        [ModelReply.tools(ToolCall(name="count_tickets", arguments={"state": "open"}))] * 4
    )
    try:
        await AIFacade(looping).chat_with_tools(
            ChatRequest(messages=(Message.user("Count them."),)), tools=tools, max_rounds=2
        )
    except AIToolError as error:
        print("round limit:", type(error).__name__, error)


if __name__ == "__main__":
    asyncio.run(main())
