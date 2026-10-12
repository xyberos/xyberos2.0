---
title: Choose a scope
path: fundamentals
lesson: 9
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals09_scopes.py
prerequisites: ["/learn/fundamentals/08-dependency-injection"]
---

# Lesson 9 — choose a scope

## What you will build

Three services that differ only in how long they live, and four lines of output that prove the
difference. Scope is the answer to one question: how many instances should exist?

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## The three answers

| Scope | Instances | Use it for |
| --- | --- | --- |
| `Scope.APP` *(the default)* | one per application | connection pools, clients, configuration-backed services |
| `Scope.REQUEST` | one per request | per-request state, a unit of work |
| `Scope.TRANSIENT` | a new one every time | stateless helpers |

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals09_scopes.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals09_scopes
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals09_scopes
    ```

## What it prints

<!-- output: fundamentals09_scopes -->
```text
app-scoped gives the same instance: True
transient gives a new instance: False
request-scoped is stable inside one request: True
request-scoped is new in the next request: True
```

Read the second line carefully, because it reads backwards: the check is
`(await app.resolve(Formatter)) is (await app.resolve(Formatter))`, and the *answer* is `False` — a
transient provider builds a new instance every time, so the two are not the same object.

## The rule that catches people out

**A longer-lived service may not depend on a shorter-lived one.** An app-scoped service cannot hold a
request-scoped instance, because that instance would outlive the request it belongs to. The graph is
refused when it is validated — before anything is built:

<!-- snippet: examples/learn_fundamentals/fundamentals09_scope_violation.py -->

<!-- output: fundamentals09_scope_violation -->
```text
ScopeViolationError: app-scoped Holder cannot depend on shorter-lived request-scoped RequestThing
```

## Common mistakes

- **Making everything app-scoped.** It works until two requests share mutable state, which is a bug
  that only appears under concurrency.
- **A transient that owns a resource.** Something with a `close` or `aclose` method cannot be
  transient, because nothing would ever close it. If it needs cleanup, it wants a real scope.
- **Using a request-scoped service outside a request.** Resolve it inside
  `async with app.request_context():`; the context is what defines the request's lifetime.

## Exercise

Predict the output before you run it, then check.

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals09_scopes
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals09_scopes
    ```

<details>
<summary>Show the answer</summary>

The line to watch is the second one: `transient gives a new instance: False`. Two resolutions of a
transient provider produce two different objects, so the identity check is `False` — and that is what
"transient" means.

Request scope is the one worth predicting carefully: within one `request_context`, the same instance
comes back twice; in the next `request_context`, it does not.
</details>

## Next

Lesson 10 reads the registry the way a debugger does: `app.diagnostics()` and `xyberos check`. Until it
is published, [the roadmap](../../roadmap.md) shows where each lesson stands.
