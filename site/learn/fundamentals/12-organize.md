---
title: Organize your project
path: fundamentals
lesson: 12
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals12_organize.py
prerequisites: ["/learn/fundamentals/04-your-first-application"]
---

# Lesson 12 — organize your project

## What you will build

Nothing new — this lesson is about where code goes. There is one convention, and it decides almost
everything else: **only the composition root imports the framework.** A service module is ordinary
Python, which is why it can be tested without an application, an event loop, or a database.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## The layout

```
myapp/
  xyberos.toml            settings, read once by the application
  src/myapp/
    __init__.py
    app.py                the composition root: create_app()
    services/             ordinary Python: no framework imports
    handlers/             route handlers: framework types allowed, no business rules
  tests/
    test_app.py
```

Three rules make it work, and they are the layout's whole content:

| Rule | Why |
| --- | --- |
| **Services import nothing from the framework** | a service can then be constructed and asserted on in one line, with no application |
| **The composition root imports everything** | there is exactly one place to read to learn what the application is made of |
| **Handlers translate, they do not decide** | a handler turns a request into a service call, so the rule it enforces is testable without HTTP |

## The code

A service module first — note what it imports:

<!-- snippet: examples/learn_fundamentals/fundamentals12_service.py -->

And the lesson's own example, which checks that claim rather than asserting it:

<!-- snippet: examples/learn_fundamentals/fundamentals12_organize.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals12_organize
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals12_organize
    ```

## What it prints

<!-- output: fundamentals12_organize -->
```text
the service module imports xyberos: False
it defines: InvoiceFormatter, InvoiceLine
and it works on its own: $12.34
```

The first line is the convention, checked against the source rather than promised. The third is the
consequence: no application was created, no provider was registered, and the service still worked.

## Common mistakes

- **A service that takes the `App`.** It can then resolve anything, which means it declares nothing —
  and the layering rule is gone in a single constructor argument.
- **Business rules in a handler.** The rule is then only reachable through HTTP, so testing it needs a
  client, a route, and a running application.
- **A service that reads configuration or the environment.** Pass the value in; the application is the
  only thing that reads settings (lesson 7).
- **Putting the composition root in `__init__.py`.** Importing the package then composes an
  application as a side effect, which breaks every test that imports anything from it.

## Exercise

Move `InvoiceFormatter` into a `services/` subpackage of your project and add a test that uses it
without an application.

<details>
<summary>Show the answer</summary>

The move needs no change to the class, which is the point of the convention: a file that imports
nothing from the framework can be relocated without being rewritten.

The test needs no `App` either: the whole assertion is
`InvoiceFormatter().format(5) == "$0.05"`, and it passes with no fixture, because there is nothing to
set up.

If that test needs a fixture to construct the class, the class has acquired a dependency it should not
have — and the layering rule is what makes the problem visible this early.
</details>

## Next

Lesson 13 writes the test file for a project like this one, and lesson 14 is about the errors you will
meet while doing it. Until it is published, [the roadmap](../../roadmap.md) shows where each lesson
stands.
