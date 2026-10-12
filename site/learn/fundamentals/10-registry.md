---
title: Understand the provider registry
path: fundamentals
lesson: 10
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals10_registry.py
prerequisites: ["/learn/fundamentals/09-scopes"]
---

# Lesson 10 — understand the provider registry

## What you will build

Nothing new — the lesson is about *reading* what you have already built. `app.diagnostics()` reports
every registered provider, its scope, whether it is eager, and where it came from, which is the first
thing to look at when a wiring question has no obvious answer.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## Three verbs, and no fourth

| Verb | Call | What it means |
| --- | --- | --- |
| Register | `app.provide(Contract, ...)` | "this is what answers `Contract`" |
| Resolve | `Annotated[Contract, Inject()]` or `app.resolve(Contract)` | "give me what the application registered" |
| Inspect | `app.diagnostics()` | "show me what is registered, and who registered it" |

There is no fourth verb, and that is deliberate: nothing looks a provider up by *name*, so a typo is a
type error rather than a runtime surprise.

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals10_registry.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals10_registry
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals10_registry
    ```

## What it prints

<!-- output: fundamentals10_registry -->
```text
providers:
  Greeter [app] from application
  RequestState [request] from application
plugins:
  (none)
```

Read one line at a time and it is a table with four columns: the **contract**, its **scope**, whether
it is **eager**, and its **source**.

| Field | Why it is reported |
| --- | --- |
| `Greeter` | the contract the provider answers, which is the key everything else resolves against |
| `[app]` | the scope: `app`, `request`, or `transient` — see [lesson 9](09-scopes.md) |
| `from application` | the source: `application`, or the plugin that registered it |
| `(none)` | there are no plugins, and the report says so rather than omitting the section |

The source column is the one that earns its keep in a real application: "which plugin registered this
provider?" is the first question a wiring problem asks, and the answer is not deducible once several
plugins are loaded.

## Common mistakes

- **Reading the report before the graph is validated.** It shows what is *registered*, not what is
  *resolvable*: `app.validate()` is the check, and the report is the map.
- **Expecting a plugin's providers to be anonymous.** They are reported with the plugin as their
  source, which is why `xyberos check` prints the same report for a real application.
- **Treating the report as an API.** It is a human-readable summary for troubleshooting. Code that
  needs the facts should read `app.diagnostics().providers`, which is a tuple of typed records.

## Exercise

Register a third provider with `eager=True`, then predict its line before running the module.

<details>
<summary>Show the answer</summary>

The new line gains `eager` inside the brackets — `[app, eager]` where the other two say `[app]` — and
it appears last, because the report follows registration order rather than sorting.

Nothing about the other lines changes, which is worth noticing: the report describes the graph you
registered, and adding a provider does not reorder or annotate the ones beside it.
</details>

## Next

Lesson 11 takes the same report out of your code and into the command line, where it belongs in a
deployment. Until it is published, [the roadmap](../../roadmap.md) shows where each lesson stands.
