"""Lesson 8, exercise — a service that depends on two others.

The answer to the lesson's exercise. The graph grows by one service and the behaviour does not
change, which is the point: adding a dependency is a wiring change, not a rewrite.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, Inject


class Repository:
    """A service with no dependencies of its own."""

    def __init__(self) -> None:
        self._names = ["ada", "linus"]

    def names(self) -> list[str]:
        """Return the stored names."""
        return list(self._names)


class Formatter:
    """The service the exercise adds."""

    def format(self, names: list[str]) -> str:
        """Return the names as one line."""
        return ", ".join(names)


class UserService:
    """A service that declares what it needs, and nothing else."""

    def __init__(
        self,
        repository: Annotated[Repository, Inject()],
        formatter: Annotated[Formatter, Inject()],
    ) -> None:
        self._repository = repository
        self._formatter = formatter

    def summary(self) -> str:
        """Return the formatted names."""
        return self._formatter.format(self._repository.names())


async def main() -> None:
    """Run the exercise's version of lesson 8."""
    app = App()
    app.provide(Repository)
    app.provide(Formatter)
    app.provide(UserService)

    async with app.lifespan():
        print("users:", (await app.resolve(UserService)).summary())


if __name__ == "__main__":
    asyncio.run(main())
