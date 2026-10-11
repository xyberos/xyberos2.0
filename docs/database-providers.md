# Writing a database provider

> Status: Phase 8. The provider contract is preview API, and this guide is for someone writing a
> *different* database backend — Postgres, MySQL, or anything else SQLAlchemy speaks. If you are using
> SQLite, read the [database operations guide](./database.md) instead.

Xyberos ships one provider ([ADR 0002](./adr/0002-configuration-and-database-stack.md)) and treats
every other database as an extension point rather than a core feature
([ADR 0016](./adr/0016-database-providers-are-an-extension-point.md)). That is a deliberate trade: a
provider maintained by the people who need it is better than three maintained by the people who do
not, and the contract is small enough that writing one is an afternoon rather than a project.

## The contract

Three members, and that is all:

```python
class DatabaseProvider(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]: ...
    def retrying(
        self, operation: TransactionOperation[T], *, attempts: int | None = None,
        base_delay: float | None = None,
    ) -> Awaitable[T]: ...
    async def health(self) -> None: ...
```

| Member | What it must do |
| --- | --- |
| `transaction()` | open a short-lived transaction on its own connection, commit when the body returns, roll back and re-raise when the body raises |
| `retrying(operation, attempts=, base_delay=)` | run an idempotent operation with a **bounded** retry for that engine's contention model, and return the operation's value |
| `health()` | run a trivial query and raise a `DatabaseError` subclass when the database cannot serve it |

The handler receives a SQLAlchemy `AsyncConnection`, which is what makes the seam portable: the
contract is *any async SQLAlchemy dialect*, not "any database". A service depending on
`DatabaseProvider` never sees a dialect, a pool, or a session.

**What the contract deliberately excludes**, so a provider cannot leak it into application code:

- ORM sessions (`AsyncSession`) — that is a choice the application makes above the provider.
- A migration engine — Alembic is driven explicitly, at deploy time
  ([database guide](./database.md#migrations)).
- Pool configuration, connection strings, and driver options — those belong to the provider's own
  settings object, the way `SqliteSettings` belongs to the SQLite one.
- Anything about isolation levels beyond the documented ones. The contract promises a short
  transaction that commits or rolls back, not a particular snapshot behaviour.

## Prove it

```python
import asyncio

from xyberos.database.testing import assert_provider_contract


def test_my_provider_satisfies_the_contract() -> None:
    async def scenario() -> None:
        provider = await my_provider(...)          # started, ready to serve
        checked = await assert_provider_contract(provider)
        print(", ".join(checked))

    asyncio.run(scenario())
```

The suite raises `AssertionError` naming the check that failed, and returns the list of checks it ran
when everything passed:

```text
health() succeeds for a working provider
transaction() commits when the body returns
transaction() rolls back and re-raises when the body raises
a failed transaction leaves the provider usable
retrying() runs the operation and returns its value
retrying() lets 4 concurrent writers finish
```

It is the *same suite* the shipped SQLite provider runs in this repository
(`tests/database/test_provider_contract.py`), and that file also proves the suite fails for a provider
that breaks the contract — a conformance suite that passes for everything would be evidence that means
nothing. Two deliberately broken providers are checked there: one that commits work a failed
transaction should have rolled back, and one whose `retrying` drops the operation's result.

The suite uses its own table (`xyberos_conformance`, or a name you pass) and drops it afterwards, so it
is safe against a scratch database and safe to run twice.

## What stays SQLite-specific

These are part of the shipped provider, not of the contract. Do not try to generalize them, and do not
expect them from another provider:

| Module or name | Why it is not in the contract |
| --- | --- |
| `SqliteSettings`, `open_database`, `sqlite_provider` | the provider's own configuration and lifecycle |
| `temporary_database` | builds a SQLite file; a different provider needs its own test double |
| `run_migrations` / `apply_migrations` | Alembic, with a *synchronous* URL, and dialect-specific revision bodies (`batch_alter_table` for SQLite) |
| PRAGMA defaults (`journal_mode`, `synchronous`, `busy_timeout`) | SQLite's contention model; another engine has its own |

## The parts that differ most between engines

Two things genuinely change meaning when you move engines, and both are worth thinking about before you
write code:

1. **`retrying` is about *your* contention model.** SQLite has one writer, so its policy retries lock
   failures. Postgres has many writers and different failure modes — serialization failures,
   deadlocks — with different retryability. A provider that inherits SQLite's assumptions will either
   retry too much or too little. This member is in the conformance suite precisely because it is the
   one that is easiest to get subtly wrong.
2. **Rollback semantics differ.** Some engines abort the whole transaction on a statement error;
   others do not. The contract only requires that a body that raises leaves no work behind, which is
   the property the suite checks.

## Register it

A provider arrives the way any other service does — already started, supplied as an instance, so the
application owns and closes it:

```python
from xyberos import App
from xyberos.database import DatabaseProvider

app = App()
app.provide(DatabaseProvider, instance=my_provider, eager=True)
app.provide(ItemService)
```

`examples/sqlite_crud` does exactly this in its test suite with the SQLite provider, so the shape is
exercised rather than described:

```python
app.provide(DatabaseProvider, instance=database)
```

## Checklist before you publish

- [ ] `assert_provider_contract` passes, and you kept its output in your test suite.
- [ ] `health()` raises a `DatabaseError` subclass when the database is unreachable, and does not
      raise when it is reachable.
- [ ] `retrying` is **bounded** — it never waits indefinitely — and its retryable failure set is
      documented.
- [ ] Cleanup is real: `aclose()` releases the engine and its connections.
- [ ] Your settings object lives in your package, not in `xyberos.database`.
- [ ] You documented what your provider does *not* support, in the same spirit as
      [the limits sections](./stability.md) here.

If you publish one, say so in your repository's README and open an issue here — the
[plugin guide](./plugins.md#the-catalogue) lists known extensions, and a provider that runs this suite
belongs on that list.
