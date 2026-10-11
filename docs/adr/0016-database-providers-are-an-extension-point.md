# ADR 0016: Database providers are an extension point, not a core feature

**Status:** accepted

## Context

Xyberos ships one database provider: SQLite through SQLAlchemy Core
([ADR 0002](0002-configuration-and-database-stack.md)). That is the right default for the project's
audience — a file, no server, no configuration — and it is also the first thing that rules the
framework out for teams whose workload outgrows a single writer.

The obvious response is to ship a second provider. That response is wrong for this project for the
same reason the auth refusal is right: a Postgres provider becomes a second thing to keep correct
against a different engine's transaction, locking, and pool semantics, and it would be maintained by
people who use neither it nor the workload it exists for. What the framework *can* do cheaply is make
the contract explicit enough that someone else can write that provider with confidence — and prove it.

The contract already exists and is smaller than it looks: `DatabaseProvider` is three members —
`transaction()`, `retrying()`, `health()` — and it hands the caller a SQLAlchemy `AsyncConnection`. The
honest scope of the seam is therefore **any async SQLAlchemy dialect**, not "any database", and saying
so precisely is more useful than promising more.

## Decision

**Ship one provider. Make the contract a documented, tested, reusable extension point.**

1. **The contract stays what it is** — transaction boundaries, a bounded retry helper, and a health
   check over an `AsyncConnection`. It deliberately does not expose ORM sessions, a migration engine, or
   pool configuration, so a provider cannot smuggle a dialect-specific API into application code.
2. **A conformance suite ships with the framework** (`xyberos.database.testing.assert_provider_contract`)
   so a third-party provider can prove it satisfies the contract in one call from its own test suite.
   A provider that passes is supported in the sense that means anything: its behaviour was checked
   against the same evidence as ours. The suite is exercised against the shipped SQLite provider, so the
   suite itself is not untested code shipped for someone else's benefit.
3. **A provider is a package, not a core addition.** Nothing about a second provider goes in
   `xyberos.database`; the guide explains what to implement, what to leave out, and which of our
   modules are deliberately SQLite-specific (`SqliteSettings`, the PRAGMA defaults,
   `temporary_database`) and therefore not part of the contract.
4. **A core provider addition would need a new ADR**, stating which dialect, who maintains it, and what
   the conformance evidence is.

**What stays SQLite-specific and is documented as such:** `SqliteSettings` and its PRAGMAs,
`sqlite_provider`, `temporary_database`, and the migration environment's expectation of a synchronous
URL. A service that depends on `DatabaseProvider` is portable; a service that depends on
`SqliteSettings` is not, and the guide says which is which.

## Consequences

- **Swapping the database is a supported path, not a promised feature.** A team that needs Postgres
  writes a provider package and runs the conformance suite; the framework does not pretend to have
  tested a database it has never opened.
- **The application-provider seam is already used in the repository.** `examples/sqlite_crud` and
  `tests/integration/test_sqlite_crud.py` supply an already-started provider with
  `app.provide(DatabaseProvider, instance=...)`, which is exactly the shape a different provider
  arrives through — so the seam is not theoretical.
- **The conformance suite is public surface** in a preview-tier module
  (`xyberos.database.testing`), which means its signature is covered by the surface test and its
  behaviour by the database suite. It is deliberately *not* in core, and importing it still requires
  the `database` extra.
- **A provider that passes the suite can still be wrong for a workload.** The suite checks the
  contract, not performance, isolation levels beyond the documented ones, or operational maturity.
  Choosing a database remains the adopter's engineering decision, and the
  [positioning page](../positioning.md) says so.
- **`retrying` semantics are part of the contract.** A provider must implement bounded retry for its own
  contention model, not inherit SQLite's. This is the one member whose meaning differs most between
  engines, which is why it is in the suite rather than left to documentation.
