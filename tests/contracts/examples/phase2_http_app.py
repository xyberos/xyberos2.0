"""Phase 2 contract for the Starlette adapter; routing is not implemented in Phase 1."""

from typing import Annotated

from xyberos import App, Inject


class UserService:
    async def list_users(self) -> list[str]:
        return []


app = App()
app.provide(UserService, factory=UserService, scope="app")


@app.get("/users")
async def list_users(users: Annotated[UserService, Inject()]) -> list[str]:
    return await users.list_users()
