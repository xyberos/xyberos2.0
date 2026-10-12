"""A second composable module: it depends on the first one's contract, not on its registration.

Importing the *type* is what depending on a contract means here, and it is the only thing this
module takes from its neighbour: it never calls `module_rates.register`, so which modules are
composed, and in which order, is the application's decision rather than this module's.
"""

from __future__ import annotations

from typing import Annotated

from starlette.requests import Request

from learn_extend.module_rates import Rates
from xyberos import App, Inject


class Pricing:
    """Quotes a price, using whatever rates the application happens to have registered."""

    def __init__(self, rates: Annotated[Rates, Inject()]) -> None:
        self._rates = rates

    def quote(self, code: str, price: float) -> float:
        """Return a price after the discount for ``code``."""
        return round(price * (1 - self._rates.discount(code)), 2)


def register(app: App) -> None:
    """Attach this module's provider and route to an application."""
    app.provide(Pricing)
    app.get("/quote")(read_quote)


async def read_quote(request: Request, pricing: Annotated[Pricing, Inject()]) -> dict[str, object]:
    """Answer one quote, reading the query string the way every handler does."""
    code = request.query_params.get("code", "")
    price = float(request.query_params.get("price", "0"))
    return {"code": code.upper(), "price": price, "quote": pricing.quote(code, price)}
