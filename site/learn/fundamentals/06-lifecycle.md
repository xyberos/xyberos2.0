---
title: Understand the application lifecycle
path: fundamentals
lesson: 6
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals06_lifecycle.py
prerequisites: ["/learn/fundamentals/05-run-your-application"]
---

# Lesson 6 — understand the application lifecycle

## What you will build

An application that fails to start, on purpose. The interesting part of a lifecycle is not the happy
path — it is what happens to the half-built application when one provider cannot be constructed.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## The states

| State | Reached when |
| --- | --- |
| `new` | `App()` has been created and providers registered |
| `validated` | `app.validate()` has checked the graph without building anything |
| `starting` | `start()` is resolving eager providers |
| `ready` | everything app-scoped and eager exists, and requests are accepted |
| `stopping` | `stop()` is releasing what the application owns |
| `stopped` | nothing is owned any more; `stop()` on a stopped application does nothing |
| `failed` | startup raised; whatever was built has been closed |

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals06_lifecycle.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals06_lifecycle
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals06_lifecycle
    ```

## What it prints

<!-- output: fundamentals06_lifecycle -->
```text
initial: new
connection acquired
connection released
startup failed: failed to construct BrokenService from application
after the failure: failed
after stop: stopped
```

Four things are happening in those six lines, and each one is a decision:

1. **The connection was acquired before the failure.** Eager providers are built in registration order,
   so the first one exists by the time the second raises.
2. **It was released anyway.** `connection released` appears *before* the failure is reported, because
   the runtime closes what it already built instead of leaving it to the garbage collector.
3. **The error names the contract, not the line.** `failed to construct BrokenService from application`
   tells you which provider failed and which source registered it. The original exception is the
   *cause* of that error, so `except ... as error: error.__cause__` is the traceback you want.
4. **`failed` is a state you can leave.** `stop()` still moves the application to `stopped`; the
   alternative would be a lifecycle you cannot recover from in a long-running process.

## Common mistakes

- **Catching the wrong exception.** A failing provider surfaces as `DependencyResolutionError`, not as
  whatever the factory raised. Catch the framework's error and read `__cause__` for the original.
- **Leaving a resource out of the runtime's ownership.** A provider built with `instance=` is *given*
  to the application rather than owned by it, so nothing closes it. Own it with a factory, or close it
  yourself.
- **Treating `failed` as fatal to the process.** It is a state: fix the wiring, or stop cleanly and
  exit — but the application will not resolve anything while it is `failed`.

## Exercise

Remove the failing provider and predict the output before running it.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_fundamentals/fundamentals06_exercise.py -->

<!-- output: fundamentals06_exercise -->
```text
initial: new
connection acquired
after start: ready
connection released
after stop: stopped
```

Two differences from the lesson, and both are the point:

- The state after startup is `ready` rather than `failed`, so the application is one you can use.
- `connection released` now happens inside `stop()` rather than during a failed startup — because a
  provider that started successfully is closed when the application stops, not when it starts. Note
  the position: the release happens *before* the state becomes `stopped`, which is what makes
  `stopped` mean "nothing is owned any more".
</details>

## Next

Lesson 7 is where configuration becomes real: a settings file, the environment, and explicit
arguments, in the order that decides which one wins. Until it is published,
[the roadmap](../../roadmap.md) shows where each lesson stands.
