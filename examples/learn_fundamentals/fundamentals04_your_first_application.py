"""Lesson 4 — your first application.

Run it with:

    python -m learn_fundamentals.fundamentals04_your_first_application
"""

from __future__ import annotations

import asyncio

from xyberos import App


class Greeter:
    """A service: an ordinary class that knows nothing about Xyberos."""

    def greet(self, name: str) -> str:
        """Return a greeting."""
        return f"Hello, {name}!"


async def main() -> None:
    app = App()
    app.provide(Greeter)

    async with app.lifespan():
        greeter = await app.resolve(Greeter)
        print(greeter.greet("world"))
        print("state:", app.state.value)


if __name__ == "__main__":
    asyncio.run(main())
