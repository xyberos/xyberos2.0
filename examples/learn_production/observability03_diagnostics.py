"""Walkthrough — what a running application can be asked about itself, and when the answer changes.

Run it with:

    python -m learn_production.observability03_diagnostics
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, Inject, Scope
from xyberos.errors import LifecycleStateError


class Prices:
    """An app-scoped capability: built once, shared, and closed by the application."""

    @property
    def source(self) -> str:
        return "a price table the application loaded"


class Quote:
    """A service that depends on it, so the graph has an edge to show."""

    def __init__(self, prices: Annotated[Prices, Inject()]) -> None:
        self._prices = prices


def main() -> None:
    """Print the state and the graph before, during, and after the application's lifetime."""
    app = App()
    app.provide(Prices)
    app.provide(Quote, source="the pricing module")
    app.provide(Prices, replace=True, source="a deployment override")

    print("state before start:", app.state.value)
    print(app.diagnostics().render().strip())

    asyncio.run(scenario(app))


async def scenario(app: App) -> None:
    """Resolve the graph while the application is up, and report what its records say."""
    async with app.lifespan():
        print("state while serving:", app.state.value)
        resolved = await app.resolve(Quote)
        print("the service resolved:", type(resolved).__name__)
        records = app.diagnostics().providers
        print("records:", ", ".join(f"{info.contract} ({info.scope})" for info in records))
        print("request scope exists too:", Scope.REQUEST.value)

    print("state after stop:", app.state.value)
    try:
        await app.start()
    except LifecycleStateError as error:
        print("starting it again:", type(error).__name__, "-", error)


if __name__ == "__main__":
    main()
