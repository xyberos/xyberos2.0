---
title: Writing a module
status: verified
---

# Writing a module

Xyberos has no module type, and that is the design rather than a gap. What it has is an application
object whose registrations are explicit, so **a module is a package that exposes one function taking
the application**. Nothing registers itself, nothing is discovered, and composition is a decision a
reader can point at.

Two properties make a module composable, and both are about what it *does not* say:

- It declares nothing about the application it lands in — no name, no settings file, no assumption
  about what else is registered.
- Its route handlers obey the three parameter rules the HTTP adapter enforces: a path segment, the
  `Request`, or `Annotated[T, Inject()]`. A query string is read from the request, never invented.

## The shape

<!-- snippet: examples/learn_extend/module_rates.py -->

`register` is the whole convention: it takes the application, attaches what this module contributes,
and returns nothing. It is deliberately not a class with a `bootstrap` method and not a decorator —
because a plain function can be read at a glance, called in a test, and called twice against two
different applications.

## Depending on a contract, not on a registration

<!-- snippet: examples/learn_extend/module_pricing.py -->

The pricing module imports `Rates` — the *type* — and never calls `module_rates.register`. That is what
depending on a contract means here: this module states which capability it needs, and the application
decides who provides it. A module that wired its own neighbours would take the composition decision
away from the application, and a test that wants to replace one of them would have nowhere to stand.

## Composing

<!-- snippet: examples/learn_extend/modules01_composition.py -->

`create_app` is the application's own module, and it is the only place that knows which pieces exist.
It takes no required arguments, which is not a style preference: `xyberos check --app pricing.app:create_app
--app-dir src` calls it, and so does an ASGI server through an import string. A factory with required
arguments is a factory neither of those can call.

<!-- output: modules01_composition -->

```text
routes: ['GET /rates/{code}', 'GET /quote']
providers:
  Rates [app] from application
  Pricing [app] from application
plugins:
  (none)
GET /rates/SAVE10 -> {'code': 'SAVE10', 'discount': 0.1}
GET /quote -> {'code': 'SAVE10', 'price': 100.0, 'quote': 90.0}
the same routes, a test's rates -> {'code': 'SAVE10', 'price': 100.0, 'quote': 50.0}
the clone is a different application: True
```

The last two lines are the payoff. `with_overrides({Rates: ...})` changes what the pricing module
sees without editing either module, because the pricing module never asked *where* `Rates` came from —
only that it exists. A second application built from the same modules and a different `Rates` is a
different application, not a mocked one.

## What belongs in a module

| Belongs | Why |
| ------- | --- |
| `app.provide(...)` for the contracts it owns | the module that constructs a capability owns its lifetime |
| Routes that read those capabilities | the handler signature is the dependency declaration |
| Constants and types other modules may import | a contract is what makes composition possible |
| Nothing about the application it is registered with | the application owns composition |

| Does not belong | Why |
| --------------- | --- |
| Calling another module's `register` | that is the application's decision, not the module's |
| Reading the environment or a settings file | configuration reaches a module as a constructor argument |
| Reaching into an internal `xyberos` module | only the public surface is a stable contract |
| Registering after startup | routes and providers are frozen once the application is ready |

**When a module should become a plugin.** The moment somebody else has to install it. A module is code
inside your application; a plugin is a package with a name, an `api_version`, and typed configuration,
which the runtime can validate, order, and attribute. The mechanics are the same `app.provide` and
`app.get` calls — which is why the next page is about the wrapper and not about a second API.

## Where to read next

- [Writing a plugin](./plugins.md) — the same registrations, packaged and versioned.
- [The provider registry](./registry.md) — scopes, factories, and overrides in detail.
- [HTTP handlers](../reference/http.md) — the parameter rules this page refuses to work around.
