"""Lesson 3 — the first model call, and what comes back with it.

Run it with:

    python -m learn_ai.ai03_first_call
"""

from __future__ import annotations

import asyncio

from xyberos.ai import AIFacade, ChatRequest, FakeModelProvider, Message, ModelReply, Usage
from xyberos.errors import AIConfigurationError

SYSTEM_PROMPT = "You are a concise support assistant. Answer in one sentence."
DEFAULT_REPLY = "Take an umbrella: rain is likely this afternoon."


def choose_provider(
    profile: str,
    *,
    model: str = "llama3.2",
    base_url: str = "http://127.0.0.1:11434",
) -> object:
    """Return the provider a profile asks for.

    The local adapter is imported inside the branch that uses it, so a deployment that never selects
    ``ollama`` does not need the extra installed.
    """
    if profile == "fake":
        return FakeModelProvider([ModelReply.ok(DEFAULT_REPLY, usage=Usage(18, 9))])
    if profile == "ollama":
        from xyberos.ai.ollama import OllamaProvider, OllamaSettings

        return OllamaProvider(OllamaSettings(model=model, base_url=base_url))
    raise AIConfigurationError(f"unknown profile {profile!r}; use 'fake' or 'ollama'")


async def ask(assistant: AIFacade) -> None:
    """Ask one question and print every part of the answer a caller may need."""
    request = ChatRequest(messages=(Message.system(SYSTEM_PROMPT), Message.user("Will it rain?")))
    response = await assistant.chat(request)

    print("reply: ", response.message.content)
    print("model: ", response.model)
    print("tokens:", response.usage.total_tokens, f"(in {response.usage.input_tokens})")


def main() -> None:
    """Run the lesson against the deterministic provider, from the profile the composition chose."""
    provider = choose_provider("fake")
    print("profile: fake - pass 'ollama' to choose_provider to use a local model instead")
    asyncio.run(ask(AIFacade(provider)))
    assert isinstance(provider, FakeModelProvider)
    print("calls: ", provider.calls)


if __name__ == "__main__":
    main()
