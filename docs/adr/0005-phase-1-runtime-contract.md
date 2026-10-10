# ADR 0005: Freeze the Phase 1 runtime contract

**Status:** accepted

## Context

Phase 1 delivered the application runtime in `src/xyberos/`. Later phases consume its
semantics directly: the HTTP adapter (Phase 2) injects request-scoped services into handlers,
plugins (Phase 3) register providers publicly, Flow (Phase 4) propagates runtime context, and
the durable executor (Phase 6) reuses the lifecycle and error conventions. These decisions
therefore need to be explicit before Phase 2 begins.

The runtime must stay thin: composition, configuration, dependency resolution, lifecycle, and
context/logging only. It must not import HTTP, database, AI, Flow, or durable-execution code.

## Decision

**Scopes.** Only `app`, `request`, and `transient` exist. A provider may depend only on a
service with an equal or longer lifetime (`app` > `request` > `transient`). `app → request`,
`app → transient`, and `request → transient` are rejected, because the consumer would capture
the dependency for its own full lifetime, which is the captive-dependency failure the rule
prevents. Per-resolution services reach handlers through handler injection (Phase 2), not
through a longer-lived provider.

**Runtime context is not authorization.** `contextvars` carry diagnostic metadata only:
correlation IDs, logger bindings, and cooperative deadline metadata. Identity, tenancy,
permissions, and transaction handles are always passed explicitly and re-authorized for
background work. Context crosses into tasks through `create_task_in_context` and into custom
workers through `capture_context_runner`.

**Startup validation, lazy construction.** `validate()` builds and checks the whole provider
graph (missing providers, cycles, illegal scope edges, unsupported annotations) without
constructing services, so configuration and graph errors surface before readiness. App-scoped
services are constructed lazily unless they opt into `eager=True`; validation still runs before
any work is accepted.

**One-shot lifecycle.** `register → validate → start → ready → stop`. An application is not
restartable after `stop()`; create a new `App`. Registration is frozen at `start()`. A partial
startup failure closes only the resources that started, in reverse dependency order, and moves
the application to `FAILED`, which never accepts work. Shutdown attempts every hook, then
raises a single aggregated `ShutdownError` naming the resources that failed.

**Explicit dependency markers.** Dependencies are declared with `Annotated[T, Inject()]`.
Parameter names are never used for injection; a required parameter without a marker fails
registration. Registration infers dependencies from the factory signature.

**Configurable defaults with an explicit precedence.** Settings resolve as explicit arguments,
then environment variables, then `xyberos.toml`, then defaults. Core settings hold no secrets,
and validation errors never echo configured values.

**Declarative Flow first.** Flow definitions stay declarative so they remain inspectable,
retryable, and traceable. An imperative or decorator Flow API is deferred until the declarative
graph and its recovery semantics are proven.

## Consequences

- Phases 2–7 build on the frozen `App`, `Inject`, `Scope`, `Settings`, `LifecycleState`, and
  error contracts; changing them requires a new ADR.
- The error taxonomy grows per phase: Phase 1 defines configuration, registration,
  dependency-resolution, and lifecycle families. HTTP, database, Flow, provider, and
  durable-state families are added by the phase that introduces them.
- A configurable shutdown drain bound and provider source attribution are deliberately left to
  Phase 2 and Phase 3, where HTTP lifespan and plugin diagnostics make them actionable.
