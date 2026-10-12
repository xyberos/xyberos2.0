"""Walkthrough — replacing a provider: what a test does, and what a deployment does.

Run it with:

    python -m learn_extend.registry02_overrides
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, Inject
from xyberos.errors import MissingProviderError


class Rates:
    """A capability that reads something the application does not control."""

    def __init__(self, table: dict[str, float]) -> None:
        self._table = table

    def discount(self, code: str) -> float:
        return self._table.get(code, 0.0)


class Pricing:
    """A service that depends on the rates and knows nothing about where they came from."""

    def __init__(self, rates: Annotated[Rates, Inject()]) -> None:
        self._rates = rates

    def quote(self, code: str, price: float) -> float:
        return round(price * (1 - self._rates.discount(code)), 2)


def production() -> App:
    """Compose the application the way a deployment does: the real rates, from configuration."""
    app = App()
    app.provide(Rates, instance=Rates({"SAVE10": 0.10}))
    app.provide(Pricing)
    return app


async def main() -> None:
    """Quote once for real, once for a test, and once for a deployment that changed its mind."""
    app = production()
    async with app.lifespan():
        pricing = await app.resolve(Pricing)
        print("the application's answer:", pricing.quote("SAVE10", 100.0))

        under_test = app.with_overrides({Rates: Rates({"SAVE10": 0.5})})
        async with under_test.lifespan():
            tested = await under_test.resolve(Pricing)
            print("the same code, a test's answer:", tested.quote("SAVE10", 100.0))
            print("the test app is a clone, not a restart:", under_test is not app)

        print("and the original is untouched:", pricing.quote("SAVE10", 100.0))

    replacement = production()
    replacement.provide(Rates, instance=Rates({"SAVE10": 0.25}), replace=True)
    async with replacement.lifespan():
        print(
            "a registration can be replaced before startup:",
            (await replacement.resolve(Pricing)).quote("SAVE10", 100.0),
        )

    try:
        app.with_overrides({str: "no such provider"})
    except MissingProviderError as error:
        print("overriding something unregistered:", error)


if __name__ == "__main__":
    asyncio.run(main())
