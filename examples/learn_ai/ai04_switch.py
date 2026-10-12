"""Lesson 4 — switch providers without touching the application.

Run it with:

    python -m learn_ai.ai04_switch
"""

from __future__ import annotations

from typing import Annotated

from starlette.requests import Request

from xyberos import App, Inject, Settings
from xyberos.ai import AIFacade, ChatRequest, FakeModelProvider, Message, ModelReply
from xyberos.http import HttpAdapter, read_json_object
from xyberos.http.testing import create_test_client

SYSTEM_PROMPT = "You are a concise support assistant. Answer in one sentence."


def create_app(*, provider: object) -> App:
    """Compose the route once. The provider is the only thing that changes between runs."""
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "ai_assistant"}}))
    app.provide(AIFacade, instance=AIFacade(provider), eager=True)

    @app.post("/ask")
    async def ask(request: Request, assistant: Annotated[AIFacade, Inject()]) -> dict[str, object]:
        payload = await read_json_object(request)
        question = str(payload.get("question", ""))
        response = await assistant.chat(
            ChatRequest(messages=(Message.system(SYSTEM_PROMPT), Message.user(question)))
        )
        return {
            "provider": assistant.name,
            "model": assistant.model,
            "answer": response.message.content,
        }

    return app


def answer(provider: object, question: str) -> dict[str, object]:
    """Send one question through the application's own route."""
    with create_test_client(HttpAdapter(create_app(provider=provider))) as client:
        return dict(client.post("/ask", json={"question": question}).json())


def main() -> None:
    """The same route, two providers, no change to the handler."""
    first = FakeModelProvider([ModelReply.ok("Short answer.")], name="provider-a", model="model-a")
    second = FakeModelProvider(
        [ModelReply.ok("A longer answer, from a different provider.")],
        name="provider-b",
        model="model-b",
    )
    for provider in (first, second):
        print(answer(provider, "Will it rain?"))


if __name__ == "__main__":
    main()
