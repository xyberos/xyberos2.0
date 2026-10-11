"""Chapter 11 — asking a model for something, safely.

Run it with:

    python examples/tutorial/chapter11_ai.py

The fake provider is what makes this chapter runnable on any machine: no service, no model, no
network. Swapping in Ollama is a configuration change, not a code change.
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
    ToolSet,
    ToolSpec,
)

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}

WEATHER_SCHEMA = {
    "type": "object",
    "properties": {"city": {"type": "string"}},
    "required": ["city"],
    "additionalProperties": False,
}


async def look_up_weather(arguments: Mapping[str, object], context: object) -> dict[str, object]:
    """A tool handler: validated arguments in, ordinary data out."""
    return {"city": arguments["city"], "celsius": 11}


async def main() -> None:
    print("--- 1. a plain question ---")
    provider = FakeModelProvider([ModelReply.ok("Hello from a fake model.")])
    assistant = AIFacade(provider)
    response = await assistant.chat(ChatRequest(messages=(Message.user("Say hello"),)))
    print("content:", response.message.content)
    print("provider calls:", provider.calls)

    print("--- 2. an answer with a shape ---")
    provider = FakeModelProvider([ModelReply.json_payload({"answer": "Take one tablet"})])
    response = await AIFacade(provider).chat(
        ChatRequest(messages=(Message.user("How much?"),), response_schema=ANSWER_SCHEMA)
    )
    print("structured:", response.structured)

    print("--- 3. letting the model ask for a tool ---")
    tools = ToolSet.of(
        Tool(
            spec=ToolSpec(
                name="weather",
                description="Look up the weather for a city",
                parameters=WEATHER_SCHEMA,
            ),
            handler=look_up_weather,
        )
    )
    provider = FakeModelProvider(
        [
            ModelReply.tools(ToolCall(name="weather", arguments={"city": "Bergen"})),
            ModelReply.ok("It is 11 degrees in Bergen."),
        ]
    )
    response = await AIFacade(provider).chat_with_tools(
        ChatRequest(messages=(Message.user("What is the weather in Bergen?"),)),
        tools=tools,
        max_rounds=3,
    )
    print("rounds:", response.rounds)
    print("final:", response.message.content)
    print("provider calls:", provider.calls)


if __name__ == "__main__":
    asyncio.run(main())
