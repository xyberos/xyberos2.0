"""Lesson 9 — the rule the runtime enforces about lifetimes.

An app-scoped service cannot depend on a request-scoped one: the request-scoped instance would
outlive the request it belongs to. The graph is refused when it is validated, before anything is
built. Kept as a file so the lesson can quote the message and the suite can prove it.
"""

from __future__ import annotations

from typing import Annotated

from xyberos import App, Inject, Scope, ScopeViolationError


class RequestThing:
    """Request-scoped: one instance per request, discarded with it."""


class Holder:
    """App-scoped by default, and longer-lived than what it asks for."""

    def __init__(self, thing: Annotated[RequestThing, Inject()]) -> None:
        self.thing = thing


def main() -> None:
    """Compose a graph that cannot be valid, and show what the runtime says."""
    app = App()
    app.provide(RequestThing, scope=Scope.REQUEST)
    app.provide(Holder)

    try:
        app.validate()
    except ScopeViolationError as error:
        print(f"{type(error).__name__}: {error}")
    else:
        raise AssertionError("the graph was accepted, so this lesson no longer tells the truth")


if __name__ == "__main__":
    main()
