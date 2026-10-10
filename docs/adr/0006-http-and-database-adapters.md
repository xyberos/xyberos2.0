# ADR 0006: Keep the HTTP and database layers behind adapters

**Status:** accepted

## Context

Phase 2 delivered a Starlette-backed HTTP adapter and a SQLite database provider. Both add
public behavior while the core runtime must stay thin and free of optional imports. Applications
must also be able to replace SQLite without rewriting business services.

## Decision

**Routes live in the runtime; compilation lives in the adapter.** `App` records immutable route
records (`xyberos.Route`) without importing an HTTP library. `HttpAdapter` validates handler
signatures, compiles endpoints, and owns request/response types, middleware, and the test client.
The runtime therefore never imports Starlette, and a second HTTP adapter is possible without
changing the runtime.

**Handler input is explicit.** A handler parameter must be an injected dependency
(`Annotated[T, Inject()]`), a path parameter declared in the route template (annotated `str` or
`int`), or the Starlette `Request`. Anything else fails registration. Request bodies and query
strings are read from the `Request`; there is no implicit coercion of arbitrary request input into
dependencies. A response is a `Response`, `None` (204), or a JSON-serializable value.

**Middleware order is fixed and documented.** Correlation ID, error normalization, dependency
request scope, application middleware, then the router. The correlation ID is bound before
everything else so logs and error responses carry it, and the request scope is opened before
application middleware so those middleware can resolve request-scoped services.

**Errors are normalized without hiding programmer errors.** `HttpError` subclasses expose their
declared status and message; every other exception becomes a generic `500` with the traceback
logged and never returned. A failure is never reported as a success, and a response that has
already started is not replaced.

**The database provider is a protocol, not a driver.** Services depend on `DatabaseProvider`,
which exposes short transaction boundaries, a bounded retry helper, and a health check. The
concrete `SqliteDatabase` is replaceable, and ORM sessions are not a framework abstraction.

**Configuration is explicit and validated up front.** Connection PRAGMAs are installed on
connection initialization, never ad hoc inside requests: foreign keys, a bounded busy timeout, an
explicit synchronous policy, and WAL journaling where the database supports it.
`journal_mode="WAL"` with `synchronous="NORMAL"` is a documented performance/durability
trade-off, not a guarantee.

**Retries are opt-in and bounded.** SQLite permits one writer at a time. `transaction()` does not
retry, so callers keep control of side effects. `retrying()` retries only the documented
transient lock failures, with a bounded budget and linear backoff, and raises
`TransientDatabaseError` when the budget is exhausted rather than waiting forever. Operations that
are not safe to repeat belong in a plain transaction with an idempotency key.

**Migrations stay Alembic and stay explicit.** Xyberos exposes configuration and a wrapper for
running migrations at deployment time; it does not build a migration engine and does not migrate
implicitly during startup. SQLite table rebuilds use batch mode.

**The application database and the future durable journal use separate files.**

## Consequences

- Phases 3–7 build on the adapter and provider contracts; changing them requires a new ADR.
- The `http` and `database` extras install independently, and `import xyberos` still pulls in no
  optional capability. An import-boundary test enforces this in a subprocess.
- The runtime gained one configurable default for this phase: `app.shutdown_timeout`, which bounds
  the shutdown drain so a leaked request context cannot hang the process indefinitely.
- Provider `source` attribution in diagnostics remains a Phase 3 item, because plugin
  registration is what makes it actionable.
