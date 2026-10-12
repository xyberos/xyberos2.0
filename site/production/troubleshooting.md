---
title: Troubleshooting
status: verified
---

# Troubleshooting

Two rules make most failures in this runtime easy to read: **every failure has a name that says what it
is**, and **almost every failure is raised where the mistake was made** — at registration, at
validation, or at startup, rather than on the request that happens to arrive second.

## The line that identifies it

<!-- snippet: examples/learn_production/troubleshooting01_errors.py -->

<!-- output: troubleshooting01_errors -->
```text
factory returns the wrong type: RegistrationError: provider factory Counter returns Counter, which is not compatible with Clock
missing provider: MissingProviderError: no provider is registered for Tock; required by Tick
dependency cycle: DependencyCycleError: dependency cycle detected: Tick -> Tock -> Tick
scope violation: ScopeViolationError: app-scoped Reporter cannot depend on shorter-lived request-scoped Counter
request scope with no request: DependencyResolutionError: request-scoped Counter requires an active request context
transient managed resource: DependencyResolutionError: transient Handle returned a managed resource; use request or app scope instead
register after start: LifecycleStateError: cannot register providers in 'ready' application state
start after stop: LifecycleStateError: cannot start an application in 'stopped' state
failed shutdown: ShutdownError: 1 shutdown problem(s): Broken
resources that failed: ('Broken',)
```

Ten lines, nine distinct mistakes, and each one names the thing that is wrong: the contract (`Clock`),
the path (`Tick -> Tock -> Tick`), the scopes on both ends (`app-scoped Reporter` … `request-scoped
Counter`), the state (`'ready'`, `'stopped'`), and for shutdown the *resource* rather than the
exception.

## The taxonomy

Every error the framework raises derives from `XyberosError`, and the intermediate classes are the ones
worth catching:

| Group | Base | Members |
| ----- | ---- | ------- |
| configuration | `ConfigurationError` | a file that cannot be read, an unknown key, a value of the wrong type |
| registration | `RegistrationError` | a factory that cannot produce its contract, two registrations without `replace=True`, an unhashable contract, a registration after startup |
| dependency graph | `DependencyError` | `MissingProviderError`, `DependencyCycleError`, `ScopeViolationError`, `DependencyResolutionError` — the first three carry the `path` that identifies where in the graph it failed |
| lifecycle | `LifecycleError` | `LifecycleStateError` for an operation that is invalid in the current state, `ShutdownError` with `failures` and `resources` for a shutdown that had problems |
| HTTP | `HttpError` | the only errors whose message reaches a client; `RequestValidationError` adds an `errors` tuple, and `status_code` is what the adapter returns |
| database | `DatabaseError` | `DatabaseConfigurationError`, `DatabaseConnectionError`, `TransactionError`, `TransientDatabaseError` |
| plugins | `PluginError` | always carries `plugin` and `phase`, and never echoes a configuration value |
| AI | `AIError` | the provider-layer taxonomy: transport, timeout, rate limit, invalid payload, model not found, unsupported capability, refusal, schema |
| durable | `DurableError` | journal, lease, conflict, version, payload, and outcome-unknown |
| workflow | `WorkflowError` | validation, execution, retry exhausted, step and workflow timeout, cancellation |

Two of those groups are markers rather than errors in their own right. `TransientError` means *a retry
policy may retry this*, and nothing else is retried, so a programming error is never silently repeated;
`AITransportError` derives from both `AIError` and `TransientError` for exactly that reason. The full
list, with the attributes each class carries, is [the reference's core runtime
page](../reference/runtime.md#errors) and its [troubleshooting
checklists](../reference/troubleshooting.md).

## What to do about each

| What you see | What it usually is | Where to look |
| ------------ | ------------------ | ------------- |
| `no provider is registered for X; required by Y` | a dependency declared in a signature with no `app.provide`, or a module never imported | the `path` in the message is the chain; `app.diagnostics()` lists what *is* registered |
| `dependency cycle detected: A -> B -> A` | two services each taking the other | break it by moving one dependency to a method argument, or by injecting a factory |
| `app-scoped X cannot depend on request-scoped Y` | a long-lived service reaching for a shorter-lived one | make the dependent service request-scoped, or pass the request-scoped value as an argument |
| `request-scoped X requires an active request context` | resolving request scope from a startup hook, a CLI, or a test outside a request | `app.request_context()` is the boundary; resolve inside it |
| `provider factory F returns T, which is not compatible with C` | the contract and the thing produced disagree | the message names both; `Annotated[C, Inject()]` on the parameter is what declares the contract |
| `transient X returned a managed resource; use request or app scope instead` | a transient provider returning something with a `close`/`aclose` | transient instances are never tracked, so they are refused rather than leaked |
| `cannot register providers in 'ready' application state` | a `provide`/`route`/`add_plugin` after `start()` | registration is a build-time act; startup freezes it |
| `cannot start an application in 'stopped' state` | restarting the same `App` object | start a new process; an `App` is not reusable after `stop()` |
| `ShutdownError: N shutdown problem(s): …` | a close hook raised | `.resources` names each one, and every other resource was still closed |
| `503` from your readiness route | the database is unreachable while the process is up | the tolerant-provider posture in [deploying it](deploy.md) |
| a `500` whose body says nothing | an exception that is not an `HttpError` | the log has the message and the traceback; [security](security.md) shows both halves |
| a `410`-style body you did not expect | an `HttpError` subclass in your own code | the `type` in the body is the class name, so it is greppable |

## The rules behind the messages

- **Validate, then construct.** `App.validate()` walks the whole graph and reports the *first* problem
  with its path. `app.start()` calls it, so a graph mistake is a failed start rather than a failed
  request. `xyberos check` runs the same code without starting anything ([deploying it](deploy.md)).
- **Fail at registration when the information is there.** A factory whose return annotation is
  incompatible with its contract is refused when it is registered, not when it is first needed.
- **Keep the cause.** `DependencyResolutionError` raised while constructing a provider keeps the original
  exception as `__cause__`, which is why `deploy04_readiness` can report `caused by
  DatabaseConnectionError` in one line.
- **Collect shutdown failures instead of raising the first.** One broken resource cannot hide the rest;
  the summary carries all of them.
- **Never rewrite diagnose-only detail into the response.** `HttpError` messages are for clients; every
  other message is for the log. The two halves of that rule are one transcript, in [security](security.md).
- **Attribute plugin failures.** Every `PluginError` carries `plugin` and `phase`, so a failure is always
  attributable to a plugin and to the part of its lifecycle it happened in.

## When the message is not enough

Three escalation steps, in order:

1. `xyberos check --app <target> --app-dir <dir>` — the graph, the plugin order, the route signatures,
   and the configuration that was loaded, without starting a process.
2. `app.diagnostics()` — the same records from inside a running process, with the `source` of every
   provider ([observability](observability.md)).
3. [The reference troubleshooting guide](../reference/troubleshooting.md) — per-area checklists for the
   runtime, HTTP, database, plugins, workflow, AI, and durable execution, including the warnings that
   mean a feature is being used below the tier it is documented at.

## Common mistakes

- **Catching `Exception` around `app.start()` and continuing.** A failed start leaves the application in
  `failed`; nothing after it will work, and the state says so ([internals](internals.md)).
- **Reading `ShutdownError` as "the application stopped badly".** It means the resources were all given a
  chance to close and some refused; `.resources` is the list to fix.
- **Adding `replace=True` to silence a duplicate registration.** Duplicate registrations are refused on
  purpose: the second one is usually the mistake, and `source` exists so the *intentional* override is
  visible in diagnostics.
- **Treating `TransientError` as "retry this" without reading the operation.** Only operations that are
  idempotent are safe to retry, which is why the database helper takes an operation rather than a
  connection.
