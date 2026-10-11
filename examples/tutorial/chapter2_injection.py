"""Chapter 2 — services that need other services.

Run it with:

    python examples/tutorial/chapter2_injection.py
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from xyberos import App, Inject, MissingProviderError


class Repository:
    """A service with no dependencies of its own."""

    def __init__(self) -> None:
        self._names = ["ada", "linus"]

    def names(self) -> list[str]:
        """Return the stored names."""
        return list(self._names)


class UserService:
    """A service that declares what it needs, and nothing else."""

    def __init__(self, repository: Annotated[Repository, Inject()]) -> None:
        self._repository = repository

    def summary(self) -> str:
        """Return the stored names as one line."""
        return ", ".join(self._repository.names())


async def main() -> None:
    app = App()
    app.provide(Repository)
    app.provide(UserService)
    app.validate()

    async with app.lifespan():
        print("users:", (await app.resolve(UserService)).summary())

    broken = App()
    broken.provide(UserService)
    try:
        broken.validate()
    except MissingProviderError as error:
        print(error)


if __name__ == "__main__":
    asyncio.run(main())
