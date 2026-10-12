"""A composable module: it registers capabilities and routes, and composes with anything.

This is the whole convention. Xyberos has no module type — what it has is an application object
whose registrations are explicit, so a module is a package that exposes one function taking the
application. Two properties make it composable:

* it declares nothing about the application it lands in — no name, no settings file, no assumption
  about what else is registered;
* its route handlers obey the three parameter rules the HTTP adapter enforces: a path segment, the
  `Request`, or `Annotated[T, Inject()]`. A query string is read from the request, never invented.
"""

from __future__ import annotations

from typing import Annotated

from xyberos import App, Inject


class Rates:
    """The capability this module contributes, and the contract other modules depend on."""

    def __init__(self, table: dict[str, float]) -> None:
        self._table = table

    def discount(self, code: str) -> float:
        """Return the discount for a code, or 0.0 for a code nobody has heard of."""
        return self._table.get(code.upper(), 0.0)


def register(app: App) -> None:
    """Attach this module's provider and route to an application, and return nothing."""
    app.provide(Rates, instance=Rates({"SAVE10": 0.10, "PARTNER": 0.25}))
    app.get("/rates/{code}")(read_rate)


async def read_rate(code: str, rates: Annotated[Rates, Inject()]) -> dict[str, object]:
    """Answer one rate: the path segment, and the capability resolved from the registry."""
    return {"code": code.upper(), "discount": rates.discount(code)}
