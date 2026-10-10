"""Executable Phase 1 contract: composition, typed injection, and lifecycle."""

import asyncio
from typing import Annotated

from xyberos import App, Inject, Scope, Settings


class UserRepository:
    def __init__(self) -> None:
        self._users: list[str] = []

    async def list_users(self) -> list[str]:
        return list(self._users)

    async def aclose(self) -> None:
        self._users.clear()


class UserService:
    def __init__(self, repository: Annotated[UserRepository, Inject()]) -> None:
        self.repository = repository

    async def list_users(self) -> list[str]:
        return await self.repository.list_users()


class RequestView:
    def __init__(self, users: Annotated[UserService, Inject()]) -> None:
        self.users = users


def build_app() -> App:
    app = App(settings=Settings.load(environ={}))
    app.provide(UserRepository)
    app.provide(UserService)
    app.provide(RequestView, scope=Scope.REQUEST)
    app.validate()
    return app


async def main() -> None:
    app = build_app()
    async with app.lifespan():
        async with app.request_context() as request:
            view = await request.resolve(RequestView)
            assert await view.users.list_users() == []


if __name__ == "__main__":
    asyncio.run(main())
