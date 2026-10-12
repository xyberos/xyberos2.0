"""Lesson 14 — bounded agent behaviour: a loop, a budget, and an escalation.

Run it with:

    python -m learn_ai.ai14_agent
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass

from xyberos import StepContext, Workflow, seconds
from xyberos.ai import (
    AIFacade,
    ChatRequest,
    FakeModelProvider,
    Message,
    ModelReply,
    Tool,
    ToolCall,
    ToolSet,
    ToolSpec,
)
from xyberos.errors import AIError

TICKETS = {"T-100": "printer is on fire"}

LOOKUP_SCHEMA = {
    "type": "object",
    "properties": {"ticket": {"type": "string"}},
    "required": ["ticket"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Budget:
    """What one run of the agent may spend. Every number here is a bound, not a target."""

    rounds: int = 2
    deadline: float = 5.0


def lookup_ticket() -> Tool:
    """The only capability the agent has: reading one ticket."""

    async def handler(arguments: Mapping[str, object], context: object) -> dict[str, object]:
        return {"title": TICKETS.get(str(arguments["ticket"]), "no such ticket")}

    return Tool(
        spec=ToolSpec(
            name="lookup_ticket",
            description="Look up one ticket's title",
            parameters=LOOKUP_SCHEMA,
        ),
        handler=handler,
    )


def agent_step(assistant: AIFacade, tools: ToolSet, budget: Budget) -> Workflow:
    """One step that runs a bounded tool loop, and escalates rather than guessing."""

    async def run(value: str, context: StepContext) -> str:
        try:
            response = await assistant.chat_with_tools(
                ChatRequest(
                    messages=(
                        Message.system("Answer using the tools. If you cannot, say you cannot."),
                        Message.user(value),
                    )
                ),
                tools=tools,
                max_rounds=budget.rounds,
            )
        except AIError as error:
            return f"escalated: {type(error).__name__}"
        return response.message.content

    return Workflow("agent", version="1", input_type=str).step(
        "answer", run, timeout=seconds(budget.deadline)
    )


async def main() -> None:
    """Two runs: one the agent answers with a tool, one it escalates."""
    tools = ToolSet.of(lookup_ticket())

    answered = FakeModelProvider(
        [
            ModelReply.tools(ToolCall(name="lookup_ticket", arguments={"ticket": "T-100"})),
            ModelReply.ok("T-100 is 'printer is on fire'."),
        ]
    )
    first = await agent_step(AIFacade(answered), tools, Budget()).run(
        input="What is ticket T-100?", timeout=seconds(10)
    )
    print("asked once:   ", first.value)

    looping = FakeModelProvider(
        [ModelReply.tools(ToolCall(name="lookup_ticket", arguments={"ticket": "T-100"}))] * 4
    )
    second = await agent_step(AIFacade(looping), tools, Budget(rounds=1)).run(
        input="What is ticket T-100?", timeout=seconds(10)
    )
    print("asked forever:", second.value)

    refusing = FakeModelProvider([ModelReply.refusal(content="I cannot help with that.")])
    third = await agent_step(AIFacade(refusing), tools, Budget()).run(
        input="What is ticket T-100?", timeout=seconds(10)
    )
    print("refused:      ", third.value)
    print("the loop is chat_with_tools, bounded by max_rounds; the runtime has no agent loop")


if __name__ == "__main__":
    asyncio.run(main())
