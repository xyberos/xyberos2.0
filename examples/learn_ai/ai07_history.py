"""Lesson 7 — conversation history is the caller's, not the facade's.

Run it with:

    python -m learn_ai.ai07_history
"""

from __future__ import annotations

import asyncio

from xyberos.ai import AIFacade, ChatRequest, FakeModelProvider, Message, ModelReply, Role

SYSTEM_PROMPT = "You are a concise support assistant."


class Conversation:
    """The messages of one conversation, kept by the application and nowhere else.

    The facade sends what it is given and remembers nothing, so *what* the next request contains is
    a decision this class makes: here, the last ``window`` messages. A real application also has to
    decide what falls out of the window — a summary, a stored fact (lesson 8), or nothing.
    """

    def __init__(self, *, system_prompt: str = SYSTEM_PROMPT) -> None:
        self._system = Message.system(system_prompt)
        self._messages: list[Message] = []

    def remember(self, role: Role, content: str) -> None:
        """Append one message to the conversation."""
        self._messages.append(Message(role=role, content=content))

    def request(self, question: str, *, window: int = 4) -> ChatRequest:
        """Record the question and return the request the model will see."""
        self.remember(Role.USER, question)
        return ChatRequest(messages=(self._system, *self._messages[-window:]))

    def record(self, answer: str) -> None:
        """Record the model's answer, so the next request can refer to it."""
        self.remember(Role.ASSISTANT, answer)


async def ask(assistant: AIFacade, conversation: Conversation, question: str) -> str:
    """Ask one question with the conversation's own window of context."""
    response = await assistant.chat(conversation.request(question))
    conversation.record(response.message.content)
    return response.message.content


async def main() -> None:
    """Two turns, and the messages the provider actually received for the second."""
    provider = FakeModelProvider(
        [
            ModelReply.ok("A refund takes three business days."),
            ModelReply.ok("Yes - that three-day window still stands."),
        ]
    )
    assistant = AIFacade(provider)
    conversation = Conversation()

    print("turn 1:", await ask(assistant, conversation, "How long does a refund take?"))
    print("turn 2:", await ask(assistant, conversation, "Does that still hold today?"))

    seen = provider.requests[-1].messages
    print("the second request carried:")
    for message in seen:
        print(f"  {message.role.value}: {message.content}")


if __name__ == "__main__":
    asyncio.run(main())
