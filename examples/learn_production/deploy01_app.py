"""The application a deployment runs: eager database, a service, and a readiness route.

Nothing here is production-only machinery, and that is the point. What makes this deployable is
that the factory takes no arguments, the database is opened at *startup* rather than on the first
request, and readiness is a route the deployment asks rather than a property the process assumes.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection
from starlette.applications import Starlette

from xyberos import App, Inject, Settings
from xyberos.database import (
    DatabaseProvider,
    SqliteSettings,
    TransactionOperation,
    open_database,
    sqlite_provider,
)
from xyberos.errors import DatabaseConnectionError, HttpError, XyberosError
from xyberos.http import HttpAdapter

#: The configuration file this application ships, read before the environment overrides it.
SETTINGS_FILE = Path(__file__).with_name("deploy.toml")

#: The one setting that is not the runtime's business, so the application reads it itself.
DATABASE_KEY = "ORDERS_DATABASE"

T = TypeVar("T")


class NotReadyError(HttpError):
    """A readiness probe that failed, in the shape a load balancer understands."""

    def __init__(self) -> None:
        super().__init__("the database is not reachable", status_code=503)


class OrderNotFoundError(HttpError):
    """A client mistake, and the only thing this application says about a missing row."""

    def __init__(self, order_id: int) -> None:
        super().__init__(f"order {order_id} does not exist", status_code=404)


class UnavailableDatabase:
    """A provider that never opened, so readiness can report it instead of a crash at startup.

    This is the difference between the two deployment postures the walkthrough compares. A handler's
    injected dependencies are resolved *before* its body runs, so a provider whose construction
    raises cannot be caught by the route that wanted to report the failure: the request becomes a
    500 with a message that says nothing. Registering this instead keeps the failure reportable —
    every call raises the original ``DatabaseConnectionError``, and `/health` turns it into a 503.
    """

    def __init__(self, error: XyberosError) -> None:
        self._error = error

    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]:
        """Refuse, the way a provider that never opened must."""
        raise self._error

    def retrying(
        self,
        operation: TransactionOperation[T],
        *,
        attempts: int | None = None,
        base_delay: float | None = None,
    ) -> Awaitable[T]:
        """Refuse on await, so the caller sees the failure rather than a missing method."""

        async def fail() -> T:
            raise self._error

        return fail()

    async def health(self) -> None:
        """Report the failure this provider was built with."""
        raise self._error

    async def aclose(self) -> None:
        """Nothing to release: nothing was opened."""


class OrderService:
    """Reads orders through the contract, so the engine behind it is somebody else's decision."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def total(self, order_id: int) -> float:
        """Return one order's total, retrying write contention, or report that it is not there."""

        async def read(connection: AsyncConnection) -> float | None:
            result = await connection.execute(
                text("SELECT total FROM orders WHERE id = :id"), {"id": order_id}
            )
            value = result.scalar_one_or_none()
            return None if value is None else float(value)

        total = await self._database.retrying(read)
        if total is None:
            raise OrderNotFoundError(order_id)
        return total


def tolerant_provider(settings: SqliteSettings) -> Callable[[], Awaitable[DatabaseProvider]]:
    """Return a factory whose database failure is a reportable state rather than a start failure."""

    async def open_tolerantly() -> DatabaseProvider:
        try:
            return await open_database(settings)
        except DatabaseConnectionError as error:
            return UnavailableDatabase(error)

    return open_tolerantly


def create_app(environ: dict[str, str] | None = None, *, eager: bool = True) -> App:
    """Build the application from configuration, with no *required* arguments.

    That last property is a deployment contract rather than a style choice: `xyberos check` and an
    ASGI server both call this factory by name, so one that needed an argument could not be named.

    ``eager`` is the deployment's posture towards a broken database, and the two are not equivalent:

    * ``eager=True`` — the database is opened at startup, so a bad path is a failure to *start*. The
      orchestrator sees a crash loop, which is what it is built to report.
    * ``eager=False`` — the process comes up and `/health` answers ``503`` until the database is
      reachable, which keeps a rolling deployment from taking every replica down at once.
    """
    overrides = environ if environ is not None else {}
    settings = Settings.load(config_path=SETTINGS_FILE, environ=overrides)
    path = Path(overrides.get(DATABASE_KEY, "orders.db"))
    database = SqliteSettings(path=path)

    app = App(settings=settings)
    if eager:
        app.provide(DatabaseProvider, sqlite_provider(database), eager=True)
    else:
        app.provide(DatabaseProvider, tolerant_provider(database))
    app.provide(OrderService)
    app.get("/orders/{order_id}")(read_order)
    app.get("/health")(health)
    return app


async def read_order(order_id: int, orders: Annotated[OrderService, Inject()]) -> dict[str, object]:
    """Answer with one order's total, or with the 404 the service raises."""
    return {"order": order_id, "total": await orders.total(order_id)}


async def health(database: Annotated[DatabaseProvider, Inject()]) -> dict[str, object]:
    """Report readiness by asking the database, not by reporting that the process is running.

    A process that answers ``200`` while it cannot reach its database is the failure mode readiness
    checks exist to prevent, so this route asks the provider and turns a refusal into a ``503`` the
    load balancer understands — with a message that is safe to expose because it says nothing about
    why. The provider the handler receives is the application's own, never a second connection.
    """
    try:
        await database.health()
    except DatabaseConnectionError:
        raise NotReadyError() from None
    return {"ready": True}


def create_asgi(*, eager: bool = True) -> Starlette:
    """Return the ASGI application a server runs, compiled from the runtime built above.

    Two entry points rather than one, because they answer different questions: an ASGI server needs
    something to serve, and `xyberos check` needs the runtime to inspect *without* serving it. The
    adapter compiles the routes into a Starlette application; the ``App`` behind it is the runtime,
    and it is the same object either way.
    """
    return HttpAdapter(create_app(eager=eager)).asgi_app
