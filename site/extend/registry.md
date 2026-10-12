---
title: The provider registry
status: verified
---

# The provider registry

A registration is a type and a lifetime, and nothing else. `app.provide(...)` says *this contract is
satisfied by this factory, owned by this scope*, and from then on every `Annotated[T, Inject()]`
parameter in the application — a route handler, a service constructor, a plugin's capability — is
filled from it. The registry is also where the framework can still say **no** cheaply, because a
missing dependency and a dependency cycle are both decidable while the application is being built.

## What a registration says

<!-- snippet: examples/learn_extend/registry01_providers.py -->

`Clock` is registered as an instance, `AuditTrail` as a class — which makes the class its own factory —
and `RequestId` at request scope. `AuditTrail`'s dependency is declared in its constructor, so no
factory argument and no manual wiring is involved: the annotation is read at registration time, and the
graph is built from what every registration declares.

<!-- output: registry01_providers -->

```text
providers:
  Clock [app] from application
  AuditTrail [app] from application
  RequestId [request] from application
plugins:
  (none)
an app-scoped instance is shared: True
its dependency was injected: ['2026-10-12T00:00:00+00:00 started']
one request context, one instance: True
a new request context is a new instance: True
an unregistered contract: no provider is registered for str
a cycle is refused at validation: dependency cycle detected: First -> Second -> First
```

The `providers:` block is not decoration: it names the contract, the scope it was registered with, and
where the registration came from. `from application` is the default source, and a provider registered
inside a plugin's `register` hook reports `from plugin:<name>` instead, so a surprising override is
attributable to the code that made it.

| Scope | Who owns the instance | When it is built | When it is closed |
| ----- | --------------------- | ---------------- | ----------------- |
| `Scope.APP` | the application | at startup, or at first resolution unless `eager=True` | application shutdown, in reverse order |
| `Scope.REQUEST` | one request context | on first resolution inside that context | when that context exits |
| `Scope.TRANSIENT` | the caller | at every resolution | nobody — so it may not return a managed resource |

Rules the registry enforces at registration rather than at first use:

- **One registration per contract.** A second `provide` for the same contract is a
  `RegistrationError` unless it is explicit: `replace=True`.
- **Instance or factory, not both.** Passing an instance *and* a factory is refused; passing a
  non-class contract with no factory is refused too, because there is nothing to build.
- **`eager` is app-scoped only.** A request-scoped eager provider is an argument about a lifetime that
  does not exist yet.
- **Injected parameters are annotated.** `Annotated[T, Inject()]`, at most one marker per parameter.
  An unannotated parameter on a factory or constructor is a mistake the registry reports instead of
  guessing.
- **A transient provider may not return a managed resource.** Nobody would own closing it, so the
  runtime refuses the instance and tells you to use request or app scope.

`validate()` runs the whole graph before anything starts, which is why the cycle above is reported as a
path — `First -> Second -> First` — rather than as a stack overflow in the middle of a request. Forward
references are legal, because a class may name a dependency that is defined later in the module.

## Replacing a provider

<!-- snippet: examples/learn_extend/registry02_overrides.py -->

What a test needs is not a restart but a *different answer from one contract*, which is exactly what
`with_overrides` is for.

<!-- output: registry02_overrides -->

```text
the application's answer: 90.0
the same code, a test's answer: 50.0
the test app is a clone, not a restart: True
and the original is untouched: 90.0
a registration can be replaced before startup: 75.0
overriding something unregistered: cannot override str because it is not registered
```

Three properties matter and all three are asserted above:

- **A clone, not a mutation.** `with_overrides` returns a new application that shares the original's
  registrations and replaces the named ones. The original keeps its answer, so a test cannot change a
  fixture another test is using.
- **A clone is not a restart.** The returned application has not been started, and its lifecycle is its
  own; when it is stopped, the providers it built are closed and the original's are untouched.
- **Only what exists can be overridden.** A contract that was never registered is refused
  (`MissingProviderError`) rather than quietly added — otherwise a typo in a test would silently change
  nothing, and the test would pass for the wrong reason.

`replace=True` on `provide` is the deployment-side cousin: a settings-driven composition can register a
default and then replace it with the configured implementation before startup. After `start()` neither
route is available; the application is immutable from that moment, which is what makes a diagnosis
about it meaningful.

## Where to read next

- [Writing a module](./modules.md) — the composable unit that registers capabilities and routes.
- [Writing a plugin](./plugins.md) — the same registrations, attributable to a named, versioned package.
- [Dependency injection](../reference/runtime.md) — the exhaustive reference for scopes, factories, and
  lifecycle hooks.
