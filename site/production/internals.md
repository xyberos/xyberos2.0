---
title: Internals
status: verified
---

# Internals

Advanced architecture, for a reader who is about to depend on the runtime's behaviour rather than just
use it. The subject is small enough to fit on one page because the runtime is deliberately small: one
application object, one provider registry, one lifecycle, and one request boundary.

## The lifecycle is a state machine, and you can watch it

<!-- snippet: examples/learn_production/internals01_lifecycle.py -->

<!-- output: internals01_lifecycle -->
```text
after construction: new
after registering: new
after validate: validated
dependency-safe order: ['First', 'Second']
after registering late: new
after start: ready
after starting twice: ready
after stop: stopped
after stopping twice: stopped
what the resources saw, in order:
  1. first created while starting
  2. second created while starting
  3. second closed while stopping
  4. first closed while stopping
```

| State | Reached by | What is allowed |
| ----- | ---------- | --------------- |
| `new` | `App()` | register providers, routes, plugins |
| `validated` | `App.validate()` | the same, plus the graph is known good until something changes |
| `starting` | `App.start()` | nothing from outside; resources are being constructed |
| `ready` | the end of `App.start()` | resolve, serve requests read-only against the registry |
| `stopping` | `App.stop()` | nothing from outside; resources are being closed |
| `stopped` | the end of `App.stop()` | nothing — the object is finished |
| `failed` | a failed `App.start()` | nothing; the failure is the state's whole meaning |

Four behaviours follow from that table, and each is visible in the transcript:

- **Registration invalidates validation.** `after registering late: new` — the validated plan is a
  statement about the registry as it was, so a new registration drops back to `new` and startup
  revalidates. There is no stale plan to be surprised by.
- **`starting` and `stopping` are observable only from inside.** The two states are read here from a
  provider factory and from a close hook respectively; no caller of `start()` or `stop()` ever sees them,
  which is why they are safe to be transient.
- **`start` and `stop` are idempotent where it matters.** Starting a `ready` application and stopping a
  `stopped` one are no-ops, so a shutdown path that may run twice does not have to be careful about it.
- **`App` is not restartable.** The end of the [observability](observability.md) transcript is
  `LifecycleStateError: cannot start an application in 'stopped' state`. A process that needs to serve
  again is a new process; the alternative — quietly reusing closed resources — is the bug this refusal
  prevents.

## Dependency-safe order, and reverse close order

`after validate: dependency-safe order: ['First', 'Second']` and the four resource events say the same
thing from two sides: **construction follows the dependency graph, closing reverses construction order.**
Plugins are stopped before app-owned resources are closed, so a plugin's `stop` can still use a provider
it registered.

The rule matters when resources depend on each other. A connection pool that a client wraps must be
closed *after* the client, and reversing construction order is how that happens without a configuration
flag. A close hook is found by name (`aclose`, then `close`) or supplied at registration with `close=`;
either way, every hook is attempted and the failures are collected ([troubleshooting](troubleshooting.md)
shows a `ShutdownError` naming its resource).

## What a request actually does

```
correlation id  →  error mapping  →  request scope  →  your middleware  →  router  →  handler
                                        │
                                        └── the boundary everything resolved for this request is
                                            created in and released at the end of
```

Inside that boundary:

1. **The handler signature is inspected once, at registration.** The adapter compiles each route into a
   callable that resolves its annotated parameters and passes them in, so a handler takes ordinary
   arguments and the framework answers where they come from (`Annotated[T, Inject()]`).
2. **Resolution checks scope in order: app, then request, then transient.** An app-scoped provider
   returns the instance constructed at startup; a request-scoped one is memoized for this request; a
   transient one is constructed per injection.
3. **The request's context is a `RequestContext`, and it owns cleanup.** Everything request-scoped is
   closed when the request's response is complete, which is what makes "request-scoped" a lifecycle
   promise rather than a naming convention.
4. **The response is converted by whoever produced it.** A handler may return a dict (JSON), a Starlette
   response, or a response-like object; the adapter passes through what it does not recognize.
5. **Errors are mapped by the pipeline, not by the handler.** An `HttpError` subclass carries a status
   code and a safe message; everything else is logged with its traceback and answered generically
   ([security](security.md)).

## Diagnostics are a view of the registry

`app.diagnostics()` returns provider records (contract, scope, eager, source) and plugin records (name,
version, state, requirements). It is a pure read — it constructs nothing and mutates nothing — which is
why it can be called before startup, while serving, and after shutdown. `xyberos check` prints the same
records plus the route table ([deploying it](deploy.md)).

For a test that needs to replace one answer without touching the application, `with_overrides` returns an
*independent clone*: the original's registry and routes are copied, the named contracts are replaced with
instances, and the clone can be started and stopped on its own. Nothing about the original changes, which
is the property [the registry page](../extend/registry.md) is built around.

## The design rules, in one list

These are the constraints the runtime holds itself to. Each one has a cost that shows up somewhere else
on this site, and each is recorded as a decision rather than a preference:

| Rule | Consequence |
| ---- | ----------- |
| The core imports nothing it does not need | capabilities live behind extras; an unused driver is not installed ([security](security.md)) |
| Configuration is read once, at composition | no `os.environ` lookups scattered through request handling |
| The provider graph is frozen at startup | diagnostics are reproducible, and a mistake is a failed start |
| Nothing is discovered implicitly | no entry-point plugin discovery, no route auto-importing, no implicit migration |
| Every request has an owner: a `RequestContext` | request-scoped resources cannot outlive their request |
| Shutdown collects failures instead of raising the first | one bad hook cannot hide the rest |
| Errors are classified at the boundary | clients get mapped messages, operators get everything else |
| Nothing is scheduled by the framework | no background thread, no timer, no metrics loop to reason about |

The decisions themselves, with the alternatives that were rejected, are in
[the runtime reference](../reference/runtime.md), [the architecture guide](../reference/architecture.md),
and the [ADR list](../reference/adr/README.md) — including
[ADR 0001 on runtime boundaries](../reference/adr/0001-runtime-boundaries.md), which is where the
"core imports nothing optional" rule is argued.

## Common mistakes

- **Holding a `RequestContext` beyond its request.** It is closed when the request ends; the dependencies
  it owned are not usable afterwards.
- **Depending on `starting`/`stopping` from outside a factory or a close hook.** They are transient by
  design; use `ready` and `stopped`, and use `app.state` if you need to know where a process is.
- **Calling `stop()` and then continuing to serve.** The object is finished by contract; the refusal to
  restart exists so this is a `LifecycleStateError` rather than an empty connection pool.
- **Reading diagnostics as a snapshot of *instances*.** It lists registrations and sources, not what has
  been constructed; use it to answer "who registered this", not "is this alive".
- **Assuming plugin order is alphabetical.** It is dependency order, and it is reported.
