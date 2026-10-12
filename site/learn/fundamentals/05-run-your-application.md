---
title: Run your application
path: fundamentals
lesson: 5
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals05_run.py
prerequisites: ["/learn/fundamentals/04-your-first-application"]
---

# Lesson 5 — run your application

## What you will build

The same application as lesson 4, run the way a deployment runs it: configuration read from a file,
startup and shutdown controlled explicitly rather than by a context manager, and the lifecycle state
visible at each step.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals05_run.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals05_run
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals05_run
    ```

The module writes its `xyberos.toml` into a temporary directory: a lesson that leaves a settings file
behind changes the next lesson's result, and a configuration lesson in particular must not depend on
what a previous run wrote.

## What it prints

<!-- output: fundamentals05_run -->
```text
configuration read from: xyberos.toml
environment: production
before start: new
after start: ready
after stop: stopped
```

## The lines that matter

| Line | What it does |
| --- | --- |
| `Settings.load(environ={}, cwd=Path(directory))` | reads `xyberos.toml` from that directory, with no environment overrides |
| `App(settings=settings)` | composes the application around the settings you resolved |
| `await app.start()` | validates, freezes the graph, and builds every eager provider |
| `await app.stop()` | stops accepting work, then releases what the application owns |
| `app.state.value` | `new`, `ready`, and `stopped` — the three states this run passes through |

**`async with app.lifespan()` is `start()` and `stop()`.** Lesson 4 used the context manager, which is
the form to prefer; this lesson uses the two calls so you can see the states between them. The context
manager also stops the application when the block *raises*, which is the reason to prefer it.

**Configuration is read once, by the application.** `app.settings` is the only place to reach it, and
nothing in a service reads the environment for itself.

## Common mistakes

- **Starting an application twice.** The second `start()` returns immediately when the state is already
  `ready` — it is not an error, and it is not a second startup either.
- **Forgetting to stop.** A stopped process releases the operating system's resources anyway, but an
  application that is stopped releases *its* own: connection pools, file handles, and background tasks.
  In a test, that is the difference between a suite that passes twice and one that passes once.
- **Reading the environment in a service.** That is what lesson 7 is for, and doing it in a service is
  how configuration becomes untestable.

## Exercise

Change the settings file so the environment is `staging`, and predict which lines of output change.

<details>
<summary>Show the answer</summary>

Only the second line changes: `environment: staging`. The states are the same, because the lifecycle
does not depend on configuration — and the first line does not change either, because the file is still
found by its name in the directory `cwd` points at.

If you instead set `XYBEROS_APP__ENVIRONMENT=staging` in the environment, nothing changes here: the
module passes `environ={}`, deliberately, so that its output does not depend on the operator's shell.
Removing that empty mapping is what lesson 7 changes. Then the environment wins.
</details>

## Next

Lesson 6 takes the same start-and-stop sequence and asks what happens when startup fails halfway.
Until it is published, [the roadmap](../../roadmap.md) shows where each lesson stands.
