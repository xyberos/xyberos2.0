"""Lesson 1 — an application that is AI-ready and needs no model to run.

Run it with:

    python -m learn_ai.ai01_ready
"""

from __future__ import annotations

from typing import Annotated

from xyberos import App, Inject, Settings
from xyberos.ai import AIFacade, FakeModelProvider, LoggingPolicy, ModelCapabilities
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

TICKETS = ["printer is on fire", "badge reader is broken"]


class TicketDesk:
    """The part of the application that has nothing to do with a model."""

    def __init__(self) -> None:
        self._tickets = list(TICKETS)

    def open_tickets(self) -> list[str]:
        """Return the open tickets."""
        return list(self._tickets)


def create_app(*, provider: object | None = None) -> App:
    """Compose the application: a service, and an AI facade behind a seam.

    ``provider`` is what a test or a deployment supplies. Passing nothing still composes a working
    application, because this lesson makes no model call at all.
    """
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "ai_assistant"}}))
    app.provide(TicketDesk, instance=TicketDesk())
    app.provide(
        AIFacade,
        instance=AIFacade(
            provider
            if provider is not None
            else FakeModelProvider([], capabilities=ModelCapabilities()),
            logging_policy=LoggingPolicy.metadata_only(),
        ),
        eager=True,
    )

    @app.get("/tickets")
    async def list_tickets(desk: Annotated[TicketDesk, Inject()]) -> list[str]:
        return desk.open_tickets()

    @app.get("/assistant")
    async def assistant_status(assistant: Annotated[AIFacade, Inject()]) -> dict[str, object]:
        health = await assistant.health()
        return {
            "provider": assistant.name,
            "model": health.model,
            "status": health.status.value,
            "detail": health.detail,
        }

    return app


def main() -> None:
    """Show that the application serves its routes with no model call at all."""
    provider = FakeModelProvider([], capabilities=ModelCapabilities())
    with create_test_client(HttpAdapter(create_app(provider=provider))) as client:
        print("tickets:  ", client.get("/tickets").json())
        print("assistant:", client.get("/assistant").json())
    print("model calls:", provider.calls)


if __name__ == "__main__":
    main()
