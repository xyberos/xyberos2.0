# Database operations guide

> Status: Phase 2. The SQLite provider is preview API and lives in the optional `database` extra.

Install it with `pip install "xyberos[database]"`, which provides SQLAlchemy 2.x Core,
`aiosqlite`, and Alembic. Importing `xyberos` never imports any of them, and importing a database
module without the extra fails with that command, not a bare `ModuleNotFoundError`.

Xyberos owns configuration, connection PRAGMAs, transaction boundaries, and shutdown. SQLAlchemy
owns the driver integration. Applications use Core statements; ORM sessions are not a required
framework abstraction.

**SQLite is the default, not the contract.** A service depends on `DatabaseProvider` — three members
over a SQLAlchemy `AsyncConnection` — so a different backend is a provider package rather than a change
to your business code. That path, and the conformance suite that proves a provider satisfies the
contract, is documented in [writing a database provider](./database-providers.md). Whether SQLite is
enough for a given workload is answered with numbers in [performance](./performance.md) and
[where Xyberos fits](./positioning.md).

## Configuration

```python
from xyberos.database import SqliteSettings

settings = SqliteSettings(
    path="var/app.db",        # a file path, or ":memory:" for tests
    foreign_keys=True,
    journal_mode="WAL",
    synchronous="NORMAL",     # explicit policy, not a hidden guarantee
    busy_timeout_ms=5000,     # bounded wait before SQLite reports a busy database
    retry_attempts=5,         # bounded retry budget for lock contention
    retry_base_delay=0.05,
)
```

| Setting | Notes |
| --- | --- |
| `path` | Relative paths resolve against the process working directory |
| `foreign_keys` | `PRAGMA foreign_keys=ON` on every connection |
| `journal_mode` | Default `WAL`; rejected for `:memory:` databases |
| `synchronous` | `OFF`, `NORMAL`, `FULL`, or `EXTRA`. `NORMAL` with WAL is fast but is a durability trade-off: a committed transaction can be lost if the operating system crashes. Choose `FULL` when that matters |
| `busy_timeout_ms` | How long SQLite waits for a lock before reporting the database as busy |
| `retry_attempts`, `retry_base_delay` | Defaults for the bounded retry helper |

Invalid values raise `DatabaseConfigurationError` rather than failing later at query time.
`settings.url` is the async URL the provider uses; `settings.sync_url` is the synchronous URL
Alembic needs. Starting the provider creates the database file's parent directory when it is
missing, so a zero-configuration default path works out of the box.

## Ownership

Register the provider under the `DatabaseProvider` protocol so services depend on the contract,
not on SQLite:

```python
from typing import Annotated

from xyberos import App, Inject
from xyberos.database import DatabaseProvider, SqliteSettings, sqlite_provider

app = App()
app.provide(DatabaseProvider, factory=sqlite_provider(SqliteSettings()), eager=True)
```

`sqlite_provider(...)` returns a zero-argument async factory. Marking it `eager=True` opens the
database, installs PRAGMAs, and runs a health check during `app.start()`, so readiness reflects a
reachable database. The provider closes itself on `app.stop()` because it exposes `aclose()`.

You can also build one explicitly and hand it over; the application then owns and closes it:

```python
database = await open_database(SqliteSettings(path="var/app.db"))
app.provide(DatabaseProvider, instance=database)
```

For tests, `xyberos.database.temporary_database()` yields a started database backed by a real
temporary file — real, not in-memory, so WAL mode and file locking behave as in production.

## PRAGMAs

PRAGMAs are installed on connection initialization through a SQLAlchemy `connect` event, never
ad hoc inside a request. `foreign_keys`, `busy_timeout`, and `synchronous` are per-connection;
`journal_mode=WAL` is a database-level setting and is skipped for in-memory databases.

## Transactions

```python
from sqlalchemy import select

from myapp.tables import items


class ItemService:
    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def list_items(self) -> list[dict[str, object]]:
        async with self._database.transaction() as connection:
            rows = (await connection.execute(select(items))).mappings().all()
        return [dict(row) for row in rows]
```

- `transaction()` opens a connection, begins a transaction, commits on success, and rolls back
  when the body raises. The body's exception propagates unchanged.
- Keep transactions short and application-defined. Do not hold a write transaction across a
  network call or other slow work, because SQLite permits only one writer at a time.
- A commit-time lock failure becomes `TransientDatabaseError`; another commit failure becomes
  `TransactionError`. Both preserve the original SQLAlchemy error as the cause.

## Concurrency and the retry policy

SQLite allows one writer at a time. Readers continue under WAL. When a writer cannot take the
lock within `busy_timeout_ms`, SQLAlchemy raises an operational error whose message reports a
locked database.

`retrying(operation)` retries only that documented class of transient lock failure, with a
bounded budget and linear backoff:

```python
async def insert_item(connection: AsyncConnection) -> int:
    result = await connection.execute(insert(items).values(name="new"))
    inserted = result.inserted_primary_key
    if inserted is None:  # typed as optional: an insert with a generated key reports one
        raise AssertionError("the insert reported no primary key")
    return int(inserted[0])


item_id = await database.retrying(insert_item, attempts=5, base_delay=0.05)
```

- Only operations that are safe to run more than once should be passed to `retrying`. A retry can
  duplicate an external side effect; use an idempotency key when the operation is not naturally
  idempotent.
- When the budget is exhausted the provider raises `TransientDatabaseError`. It never hides an
  indefinitely blocked write, and there is no unbounded wait.
- `retrying` is opt-in. `transaction()` does not retry, so callers stay in control of side
  effects.

Keep the application database and the future durable journal in **separate files** with separate
configuration, so a retrying workflow cannot lock up the application's tables.

## Migrations

Xyberos does not build a migration engine. Alembic remains the tool, driven explicitly at
deployment time rather than inside application startup:

```python
from pathlib import Path

from xyberos.database import SqliteSettings, run_migrations

settings = SqliteSettings(path="var/app.db")
run_migrations(Path("migrations"), url=settings.sync_url)          # synchronous, explicit
# or, from async code that must not block the event loop:
# await apply_migrations(Path("migrations"), url=settings.sync_url)
```

Alembic needs the **synchronous** URL because its engine is synchronous. SQLite cannot alter most
columns in place, so use `op.batch_alter_table(...)`, which rebuilds the table; the example in
`examples/sqlite_crud/migrations/` exercises a batch migration in the test suite so the rebuild
behavior is proven before it reaches production data. Run migrations with
`python examples/sqlite_crud/migrate.py [path]` to see the whole flow.

## Collection queries

A collection endpoint usually needs the same three things: the caller's filters, the caller's sort order,
and one page of rows. [`xyberos-crud`](https://github.com/xyberos/xyberos-plugins/tree/master/crud) turns a
query string into a bounded statement: a `PageRequest` is clamped to the deployment's maximum, and a field
name is resolved only through the allowlist the caller supplies — a dictionary key, never SQL text.

```python
from xyberos_crud import CrudSettings, Query, fetch_page

FILTERABLE = {"status": orders.c.status, "created_at": orders.c.created_at}
SETTINGS = CrudSettings(max_limit=100, default_limit=25)

query = Query.from_parameters(dict(request.query_params), filterable=FILTERABLE, settings=SETTINGS)
page = await fetch_page(provider, select(orders), query, filterable=FILTERABLE, settings=SETTINGS)
```

It is a package beside this line rather than a core module because the operator set is policy, and it
returns a statement rather than entities — it is not an ORM
([ADR 0023](./adr/0023-crud-package-and-the-dx-refusals.md)).

## Testing

```python
from xyberos.database import temporary_database


async def test_writes_are_atomic() -> None:
    async with temporary_database() as database:
        async with database.transaction() as connection:
            await connection.execute(insert(items).values(name="kept"))

        with pytest.raises(RuntimeError):
            async with database.transaction() as connection:
                await connection.execute(insert(items).values(name="lost"))
                raise RuntimeError("abort")

        async with database.transaction() as connection:
            names = (await connection.execute(select(items.c.name))).scalars().all()

        assert names == ["kept"]
```
