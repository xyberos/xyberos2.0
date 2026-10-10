# Runtime guide

> Status: Phases 1–5. This guide documents the preview runtime surface reached through the
> stable `xyberos` import root. Preview APIs may change in a `0.x` minor release with upgrade
> notes. The frozen contract is recorded in
> [ADR 0005](./adr/0005-phase-1-runtime-contract.md); see
> [the implementation plan](./implementation.md) for phase scope and
> [ADR 0001](./adr/0001-runtime-boundaries.md) for the runtime boundary. HTTP and database
> support are documented separately in [the HTTP guide](./http.md) and the
> [database operations guide](./database.md).

Xyberos core composes an application from explicit, typed provider registrations. It owns
application configuration, dependency injection, lifecycle, and context/logging helpers. It
does not import HTTP, database, AI, Workflow, or durable-execution code.

## Composing an application

```python
from typing import Annotated

from xyberos import App, Inject, Scope, Settings


class UserRepository:
    async def list_users(self) -> list[str]:
        return []

    async def aclose(self) -> None:
        ...


class UserService:
    def __init__(self, repository: Annotated[UserRepository, Inject()]) -> None:
        self.repository = repository

    async def list_users(self) -> list[str]:
        return await self.repository.list_users()


class RequestView:
    def __init__(self, users: Annotated[UserService, Inject()]) -> None:
        self.users = users


def build_app() -> App:
    app = App(settings=Settings.load())
    app.provide(UserRepository)
    app.provide(UserService)
    app.provide(RequestView, scope=Scope.REQUEST)
    app.validate()
    return app
```

An executable version of this example is compiled, type-checked, and run in CI from
`tests/contracts/examples/phase1_minimal_app.py`.

## Providers and dependency declaration

`App.provide(contract, factory=None, *, instance=..., scope=..., eager=..., close=..., replace=...)`

- `contract` is a class, or any other hashable key, that identifies the service.
- Supply either a `factory` callable or an already-built `instance`, never both.
- A class contract with no factory is constructed directly from that class.
- When both the contract and the factory are classes, the factory must be a subclass of the
  contract (protocol contracts skip this check).
- Dependencies are inferred from the factory signature. Every required parameter must be
  annotated with an explicit marker: `Annotated[T, Inject()]`, where `T` is the dependency
  contract. Use `Annotated[T, Inject(contract=key)]` when the dependency is keyed by an
  opaque value such as a string.
- Dependencies are never resolved by parameter name. A required parameter without a marker
  fails registration, as do `*args` and `**kwargs` factories.
- Duplicate registrations fail unless `replace=True` is passed explicitly for configuration
  or a test override.
- A supplied `close` hook takes precedence over an instance `aclose()`/`close()` method.

## Scopes

| Scope | Lifetime | Managed resources |
| --- | --- | --- |
| `app` | one instance per `App` | built lazily unless `eager=True`; closed on `App.stop()` |
| `request` | one instance per `RequestContext` | closed when the request context exits |
| `transient` | a new instance for every resolution | not owned; may not return a managed resource |

A provider may only depend on a service with an equal or longer lifetime. An app-scoped
service may not capture a request- or transient-scoped service, and a request-scoped service
may not capture a transient one; validation reports the offending resolution path.

## Lifecycle

```text
register -> validate -> start -> ready -> stop
```

- `App.validate()` builds and validates the provider graph without constructing services. It
  reports missing providers, dependency cycles, illegal scope edges, and unsupported
  annotations, and includes the resolution path and registration source in the error.
- `App.start()` validates if needed, freezes registration, and constructs eager app-scoped
  services in dependency order. Registration and resolution are rejected until the state is
  `READY`.
- If startup fails part way through, only the resources that started successfully are closed,
  in reverse dependency order, and the state becomes `FAILED`. A failed application never
  accepts work. If that cleanup also fails, the startup error is preserved as the cause of a
  `ShutdownError`.
- `App.stop()` waits for in-flight request contexts, then closes app-owned resources in
  reverse dependency order. Every hook is given a chance to run; failures are collected and
  raised together as `ShutdownError` after cleanup completes, and `ShutdownError.resources`
  names the resources that failed. Set `app.shutdown_timeout` to bound how long the drain waits;
  a timeout is reported as a shutdown problem instead of hanging the process.
- `App.lifespan()` is an async context manager that starts and stops the application.
- `App.request_context()` is an async context manager that owns a `RequestContext`. Resolve
  request-scoped dependencies through it, and it closes them when the block exits. If the
  block raises and cleanup also fails, the cleanup error is raised with the block error
  preserved as its context.
- The lifecycle is one-shot: an application cannot be restarted after `stop()`. Create a new
  `App` to run again.
- An `App` instance is bound to the single event loop that starts it, because its
  synchronization primitives are loop-bound. Create, start, and stop it inside one loop.

## Resolution

`App.resolve(contract)` returns the app- or active-request-scoped instance for a class
contract with its concrete type. `RequestContext.resolve(contract)` resolves within a request
boundary. Transient providers are constructed per call.

Errors preserve the root cause and the resolution path:

```python
DependencyResolutionError: failed to construct Service from application
```

## Test overrides

`App.with_overrides({contract: value})` returns an independent `App` clone whose registrations
are copied and whose listed contracts resolve to the supplied values. The original application
is never mutated, and overrides cannot leak between applications or parallel tests.

## Configuration

Settings load from `xyberos.toml` (stdlib `tomllib` on Python 3.11+, `tomli` on 3.10). The
precedence, from highest to lowest, is explicit arguments, then environment variables, then
the configuration file, then defaults.

- `Settings.load(config_path=..., environ=..., overrides=..., cwd=...)`.
- `app.name`, `app.environment`, and `app.debug` identify the application; `app.shutdown_timeout`
  optionally bounds the shutdown drain in seconds.
- `XYBEROS_CONFIG` selects an explicit file path; a file passed as `config_path` must exist.
- `XYBEROS_` variables map to nested settings with `__`: `XYBEROS_APP__DEBUG=true`.
- Unknown settings, incompatible types, conflicting environment names, and an unsupported
  `schema_version` are rejected with a field-level `ConfigurationError`.
- Optional capabilities own their own sections. `settings.plugin_options(name)` and
  `settings.ai_options(name)` return a named section as a plain mapping (`[plugins.metrics]`,
  `[ai.ollama]`) with the same precedence, lowercasing, and `XYBEROS_AI__OLLAMA__MODEL`-style
  environment mapping. Core keeps the contents opaque: the capability interprets its own keys and
  rejects the ones it does not know.
- Keep secrets in environment variables; core settings hold no secrets, and error messages
  never echo configured values.

## Routes

The runtime records routes without importing an HTTP library:

```python
@app.get("/items")
async def list_items(items: Annotated[ItemService, Inject()]) -> list[str]:
    return await items.list_items()
```

`get`, `post`, `put`, `patch`, and `delete` are decorators, and
`app.route(method, path, handler, name=...)` registers a handler directly. Records are
immutable `xyberos.Route` values whose handlers are compiled by an adapter. Registration is
rejected after `app.start()`, and duplicate method+path or duplicate route names are refused.
Handler signatures, request/response types, and middleware belong to the adapter; see
[the HTTP guide](./http.md).

## Plugins

Trusted, in-process plugins extend an application explicitly:

```python
app.add_plugin(GreetingPlugin(), config={"greeting": "hi"})
```

A plugin declares a unique name, an optional plugin API version and dependency list, an optional
typed configuration schema, and a `register` hook that contributes providers and routes. Its
requirements must already be registered, so plugin order is deterministic. See
[the plugin guide](./plugins.md).

`App.diagnostics()` reports the source of every active provider (`application`, `test override`, or
`plugin:<name>`) and the plugin order, and `render()` formats it for troubleshooting.

## Context and logging

Context values are stored in `contextvars` and are diagnostic only. Never use them for
identity, tenancy, authorization, or transaction handles.

- `bind_context(**values)` temporarily adds values; `get_context()` returns an independent
  copy of the current context.
- `bind_correlation_id(value)` / `get_correlation_id()` carry the correlation ID.
- `bind_deadline(seconds)` / `get_deadline()` carry cooperative deadline metadata for callers
  such as the Workflow executor.
- `create_task_in_context(coroutine)` creates an `asyncio` task that inherits the caller's
  context on every supported Python version.
- `capture_context_runner(func, *args)` returns a zero-argument callable bound to a copy of
  the current context. Build it in the originating context and invoke it from a thread or
  other custom worker so the context crosses the boundary deliberately. Plain threads do not
  inherit context.
- `ContextLogFilter` attaches the current context to log records as `xyberos_context`.

## Errors

Phase 1 raises these types, all rooted at `XyberosError`:

| Error | Raised for |
| --- | --- |
| `ConfigurationError` | invalid or unreadable configuration |
| `RegistrationError` | invalid, ambiguous, or frozen provider registration |
| `DependencyError` | base class carrying a resolution `path` |
| `MissingProviderError` | a declared dependency has no provider |
| `DependencyCycleError` | provider registrations form a cycle |
| `ScopeViolationError` | a longer-lived service captures a shorter-lived one |
| `DependencyResolutionError` | a provider cannot create a valid instance |
| `LifecycleError` | base class for lifecycle transition failures |
| `LifecycleStateError` | an operation is invalid in the current state |
| `ShutdownError` | one or more managed resources failed to close; `.resources` names them |

## Import and typing guarantees

- `xyberos` re-exports the core runtime and never imports optional capabilities; the `http` and
  `database` extras are imported only by their own subpackages.
- Only names re-exported from `xyberos` are stable import paths; every other module is internal
  and may change without notice.
- The package ships `py.typed` and is checked with `mypy --strict`; injected annotations are
  preserved with `include_extras=True`.

## Later phases

HTTP support is provided by the optional `http` extra ([guide](./http.md)) and the SQLite
provider by the optional `database` extra ([operations guide](./database.md)); plugins, the
in-process workflow engine, and the provider-neutral AI facade are part of core
([plugin guide](./plugins.md), [workflow guide](./workflow.md), [AI guide](./ai.md)). Only vendor
adapters sit behind extras — `ollama` today — and durable execution arrives in a later phase. See
[the implementation plan](./implementation.md#detailed-phase-by-phase-execution-plan).
