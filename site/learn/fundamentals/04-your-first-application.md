---
title: Your first application
path: fundamentals
lesson: 4
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals04_your_first_application.py
prerequisites: ["/learn/fundamentals/01-what-is-xyberos"]
---

# Lesson 4 — your first application

## What you will build

The smallest application that is still an application: a service, one registration, a lifetime, and one
resolution. Lesson 1 printed what the runtime is made of; this is the shape you will repeat in every
application you write from here.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md): Python 3.10 or newer, and Xyberos. This lesson needs
no optional extra.

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals04_your_first_application.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals04_your_first_application
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals04_your_first_application
    ```

`PYTHONPATH` is only there because the example lives in this repository's `examples/` directory instead
of in an installed package. In your own project the file is yours, so the second line becomes
`python app.py`.

## What it prints

<!-- output: fundamentals04_your_first_application -->
```text
Hello, world!
state: ready
```

## The lines that matter

| Line | What it does |
| --- | --- |
| `app = App()` | creates the application: a composition root, not a container you look things up in |
| `app.provide(Greeter)` | registers `Greeter` as a service, keyed by its own class |
| `async with app.lifespan():` | starts the application, and stops it when the block ends |
| `await app.resolve(Greeter)` | asks the application for the service |
| `app.state.value` | `ready`, because that line runs inside the lifespan |

Two of those are worth pausing on.

**The service knows nothing about the framework.** `Greeter` is an ordinary class: no base class, no
decorator, no import. Everything the runtime needs is in the composition root — `App()`,
`app.provide`, `app.resolve`.

**`resolve` is asynchronous.** The `await` is not decoration: the runtime may have to *construct* the
service, and construction is allowed to be asynchronous.

## Common mistakes

- **Forgetting `await`.** `app.resolve(Greeter)` without it returns a coroutine, and the next line
  fails with `'coroutine' object has no attribute 'greet'`.
- **Resolving before the lifespan starts.** Outside `async with app.lifespan():` you get
  `LifecycleStateError`, and the state is `new` rather than `ready`.
- **Looking for a container.** There is no `get("Greeter")`, and no lookup by name anywhere. A service
  that needs another service declares it in its constructor — that is [lesson 8](08-dependency-injection.md).

## Exercise

Make the greeting say your name instead of `world`.

<details>
<summary>Show the answer</summary>

Change one line:

<!-- snippet: examples/learn_fundamentals/fundamentals04_exercise.py -->

The output becomes `Hello, Ada!`, and the second line is unchanged. Regenerating the page shows the
answer's own output, because the answer is a file the suite runs like any other:

<!-- output: fundamentals04_exercise -->
```text
Hello, Ada!
state: ready
```
</details>

## Next

Lesson 5 runs an application the way a deployment does — with a settings file, a configuration
environment, and a shutdown path. Until it is published, [the roadmap](../../roadmap.md) shows where
each lesson stands.
