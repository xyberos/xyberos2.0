---
title: Read `xyberos check`
path: fundamentals
lesson: 11
tier: built-in
status: verified
verify: command
command: xyberos check --app fundamentals11_app:create_app --app-dir examples/learn_fundamentals
example: examples/learn_fundamentals/fundamentals11_app.py
prerequisites: ["/learn/fundamentals/10-registry"]
---

# Lesson 11 — read `xyberos check`

## What you will build

Nothing: this lesson reads the report for an application that already exists. `xyberos check` is the
same validation the application performs at startup — `App.validate()` — run without beginning to
start, which is what makes it usable in continuous integration.

## What you need

Xyberos with the `http` extra, because the application being checked registers routes.

## The application being checked

<!-- snippet: examples/learn_fundamentals/fundamentals11_app.py -->

That is the shape `xyberos new` writes: a composition root, one service, and two routes. Nothing about
it is special, which is the point — `check` is useful on an ordinary application.

## The command

=== "PowerShell"

    ```powershell
    xyberos check --app fundamentals11_app:create_app --app-dir examples/learn_fundamentals
    ```

=== "POSIX"

    ```bash
    xyberos check --app fundamentals11_app:create_app --app-dir examples/learn_fundamentals
    ```

## What it prints

<!-- output: cli-check-app -->
```text
settings: xyberos (development), schema_version 1, debug False
application: fundamentals11_app:create_app
provider graph: valid
providers:
  Greeter [app] from application
plugins:
  (none)
routes: 2 (handler signatures valid)
```

Five answers, in the order a deployment wants them:

| Line | What it tells you |
| --- | --- |
| `settings: …` | which configuration was resolved, and from the discovered file — not the current directory |
| `application: …` | which target was called |
| `provider graph: valid` | `App.validate()` passed, so nothing is missing and no scope rule is broken |
| `providers: …` | the same report [lesson 10](10-registry.md) printed from code, including the sources |
| `routes: 2 (handler signatures valid)` | every handler was compiled, so each parameter is injectable |

The last line is the one you cannot get from `validate()` alone: route signatures are checked by the
HTTP adapter, and a handler that declares something the adapter cannot supply is a startup failure.
`check` reports it without binding a port.

## The flags worth knowing

| Option | Why it exists |
| --- | --- |
| `--app module:attribute` | a *factory* that returns an `App`; it is called, and nothing is started |
| `--app-dir DIR` | makes a `src` layout importable without installing it |
| `--config PATH` | checks a specific settings file instead of the discovered one |

## Common mistakes

- **Pointing `--app` at the ASGI application.** `check` says so explicitly rather than guessing: an
  ASGI application is built from an `App` with `HttpAdapter(app).asgi_app`, so point it at the `App` or
  at the factory that builds one.
- **Running it without the extra the application needs.** A missing extra reports the extra to install;
  `check` never silently skips a route it cannot compile.
- **Expecting it to catch runtime failures.** A valid graph is not a working application: a provider
  whose factory raises on construction is only discovered when something is actually built.

## Exercise

Run `check` with no `--app` at all, and read what it does *not* claim.

<details>
<summary>Show the answer</summary>

```powershell
xyberos check
```

The report stops after the settings line and says
`application: not inspected (pass --app module:attribute)`. It does not pretend to have validated an
application it never looked at — which is the habit worth taking from this lesson: a report should say
what it checked, and what it did not.
</details>

## Next

Lesson 12 is about where code goes: the one convention that decides which module may import the
framework. Until it is published, [the roadmap](../../roadmap.md) shows where each lesson stands.
