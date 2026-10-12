"""Lesson 4, exercise — the greeting says your name.

The answer to the lesson's exercise, kept as a file rather than as a block on the page: the page
includes it by path and the suite runs it, so the answer cannot rot while the lesson stays correct.
Nothing is new here except one argument.
"""

from __future__ import annotations

import asyncio

from xyberos import App


class Greeter:
    """A service: an ordinary class that knows nothing about the runtime."""

    def greet(self, name: str) -> str:
        return f"Hello, {name}!"


async def main() -> None:
    """Run the exercise's version of lesson 4."""
    app = App()
    app.provide(Greeter)

    async with app.lifespan():
        greeter = await app.resolve(Greeter)
        print(greeter.greet("Ada"))
        print("state:", app.state.value)


if __name__ == "__main__":
    asyncio.run(main())
