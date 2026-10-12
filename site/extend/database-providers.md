---
title: Writing a database provider
status: verified
---

# Writing a database provider

Xyberos ships one database provider — SQLite — and what makes that a design rather than a limitation is
that nothing above it depends on it. A service depends on `DatabaseProvider`, a protocol with three
members, so a different engine is a different registration rather than a different import, as long as
those three members keep their promises.

```python
class DatabaseProvider(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[AsyncConnection]: ...
    def retrying(self, operation, *, attempts=None, base_delay=None) -> Awaitable[T]: ...
    async def health(self) -> None: ...
```

That is the contract. What follows is a provider written out longhand against it, and then the suite
that decides whether it is telling the truth.

## The provider

<!-- snippet: examples/learn_extend/sql_provider.py -->

It is about a hundred lines over the same SQLAlchemy async engine the shipped provider uses, because the
goal is to show the *shape* the contract asks for rather than to be clever. Swap `sqlite+aiosqlite` for
another SQLAlchemy async dialect and the same class is a provider for that database; services depend on
the protocol, so none of them change. The shipped provider adds settings, WAL tuning, a documented error
taxonomy, and a factory for dependency injection — conveniences on top of this, none of which change what
a service may assume.

## The conformance suite

<!-- snippet: examples/learn_extend/provider01_contract.py -->

<!-- output: provider01_contract -->

```text
the conformance suite passed 6 checks:
  - health() succeeds for a working provider
  - transaction() commits when the body returns
  - transaction() rolls back and re-raises when the body raises
  - a failed transaction leaves the provider usable
  - retrying() runs the operation and returns its value
  - retrying() lets 4 concurrent writers finish
aclose() released the engine; the application's shutdown is what calls it
a provider that commits rolled-back work is refused: a transaction that raised did not roll its work back
```

`assert_provider_contract(provider, table="provider_walkthrough")` builds its own table, runs those six
checks, drops the table, and returns the checks it ran — so it is safe against a scratch database and
safe to run twice. The name is worth reading twice, though, because the second half of the transcript is
the part that makes the first half mean anything: the suite is also given a provider that commits work a
failed transaction should have rolled back, and it **refuses** it.

`CommitsOnFailure` is a small wrapper: it delegates everything to a working provider and commits in the
`except` branch. Nothing about it looks wrong at a call site — the context manager yields a connection
and the work is written — which is exactly why the suite asserts the rollback rather than trusting it.
This repository checks both directions for the shipped provider too
(`tests/database/test_provider_contract.py`): the real one passes, and two deliberately broken ones fail.

## The semantics behind the checks

| Promise | What it means for an implementation | What breaks without it |
| ------- | ----------------------------------- | ---------------------- |
| `transaction()` commits when the body returns | the commit happens after the body, not around it | silent data loss that only appears under concurrency |
| `transaction()` rolls back and re-raises on error | the original exception reaches the caller unchanged | a caught error that looks handled while the write is half-applied |
| a failed transaction leaves the provider usable | the next transaction works on the same instances | a poisoned pool that fails every later request |
| `retrying()` returns the operation's result | the value is not swallowed by the retry loop | a `None` where a row was expected, found much later |
| `retrying()` keeps a bounded budget | a lock becomes an error, not an outage | an unbounded wait inside a request |
| `health()` raises on a broken connection | readiness reflects connectivity, not intent | a container that reports healthy while it cannot serve |

Two details in the walkthrough are contract terms rather than incidentals. The commit is wrapped so that
a *commit* failure is rolled back and mapped before it is raised: a transaction that cannot commit has
not committed, and a caller should not have to guess. And `retrying` retries **only** the documented
transient failure — write contention, mapped to `TransientDatabaseError` — with a budget that grows
linearly. Any other error is raised on the first attempt, because retrying a bug is how a small fault
becomes a long one.

Errors are mapped onto the framework's taxonomy rather than leaked as driver exceptions:

| Situation | The provider raises |
| --------- | ------------------- |
| the database cannot answer a trivial query | `DatabaseConnectionError` |
| a commit failed for a reason that will not improve | `TransactionError` |
| a write was refused because another writer holds the lock | `TransientDatabaseError` |
| anything else the driver reports | a `DatabaseError` subclass, never a raw driver error |

That mapping is what makes `retrying` meaningful: the only thing it knows how to retry is the one
transient case, and an application's own error handling sees a framework error rather than a vendor one.

## Registering it

A provider is an app-scoped capability like any other: the application's shutdown closes it if it has an
`aclose` or `close` method, and every service that declares `Annotated[DatabaseProvider, Inject()]` gets
the same instance.

<!-- snippet: examples/learn_extend/provider02_registration.py -->

<!-- output: provider02_registration -->

```text
providers:
  DatabaseProvider [app, eager] from application
  Inventory [app] from application
plugins:
  (none)
a service counted its own rows: 3
the service asked the provider whether it was ready: True
after shutdown, the same question answers: False
```

Four things in that transcript are worth naming. The provider is registered under the **protocol**, not
under the class it was written as, so services depend on `DatabaseProvider` and a different engine is a
different registration rather than a different import. It is marked **`[app, eager]`**, because
`eager=True` opened the database at startup: a misconfigured path is a failure to start rather than a
failure on the first request. `Inventory` opens its own transactions and delegates retrying, and knows
nothing else about the engine. And after `app.lifespan()` exits, the same readiness question answers
`False` — the application closed an engine it owns, which is the behaviour that keeps a test suite from
leaking connections across cases.

A provider is usually registered as an instance that is already started — `app.provide(DatabaseProvider,
instance=my_provider, eager=True)` — because that is the shape an application's own settings code
produces. The factory above is the same thing one step earlier: the runtime awaits the factory, so both
arrive at the same place, and `app.with_overrides({DatabaseProvider: ...})` replaces either in a test
with no other change.

## Before you publish one

- **Pass the suite.** `assert_provider_contract` in your own test file, against the engine you support.
- **Refuse breakage.** Keep the two broken-provider cases somewhere in your suite, the way
  `tests/database/test_provider_contract.py` does. A conformance suite that passes for everything is
  evidence that means nothing.
- **Map errors, do not leak them.** A driver exception that reaches application code ties it to your
  engine.
- **Document the dialect specifics.** Concurrency limits, isolation behaviour, and what "transient"
  means for your engine are yours to state; the reference lists the parts that differ most.
- **Publish it as a package**, and point readers at your provider from your own documentation. The
  framework will not discover it, and it will not pretend to.

## Where to read next

- [Writing a database provider](../reference/database-providers.md) — the exhaustive reference: the
  checklist, dialect differences, and what stays SQLite-specific.
- [The provider registry](./registry.md) — scopes, eager factories, and overrides.
- [Database](../reference/database.md) — what the shipped provider offers an application.
