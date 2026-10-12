---
title: Use dependency injection
path: fundamentals
lesson: 8
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals08_dependency_injection.py
prerequisites: ["/learn/fundamentals/07-configuration"]
---

# Lesson 8 — use dependency injection

## What you will build

Two services, where one needs the other. Then the same graph with a registration missing, because the
interesting part of dependency injection is not how it works when it is right — it is what happens when
it is wrong.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals08_dependency_injection.py -->

A service declares what it needs in its constructor, with a type annotation and an `Inject()` marker.
That is the whole mechanism: nothing looks anything up, and nothing depends on a parameter's *name*.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals08_dependency_injection
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals08_dependency_injection
    ```

## What it prints

<!-- output: fundamentals08_dependency_injection -->
```text
users: ada, linus
no provider is registered for Repository; required by UserService
```

The second line is the important one. It is the same file that produced it: after the working
application stops, the module composes a second one, registers `UserService` without its
`Repository`, and lets `app.validate()` fail on purpose.

## The lines that matter

| Rule | Why it is a rule |
| --- | --- |
| Every required parameter needs `Annotated[T, Inject()]` | dependencies are read from the type, so nothing depends on a parameter's name |
| `app.validate()` checks the whole graph without building anything | a wiring mistake is a startup error, not a first-request error |
| The error names the consumer, not just the missing piece | `required by UserService` tells you where to look, which is usually enough to fix it without debugging |

## Common mistakes

- **Registering the consumer and not the dependency.** That is the second line of output, and
  `MissingProviderError` is raised by `validate()`, `start()`, or the first resolution — whichever
  comes first.
- **Reaching for a container.** There is no lookup by name and no service locator. If a service needs
  something, it says so in its constructor.
- **Passing the application into a service.** A service that holds the `App` can resolve anything,
  which is the same thing as having no dependency declaration at all.

## Exercise

Add a `Formatter` service that `UserService` depends on, and have `summary()` use it.

<details>
<summary>Show the answer</summary>

<!-- snippet: examples/learn_fundamentals/fundamentals08_exercise.py -->

The output does not change — and that is the point of the exercise: the graph grew by one service and
the behaviour stayed the same.

<!-- output: fundamentals08_exercise -->
```text
users: ada, linus
```
</details>

## Next

Lesson 9 answers the next question: how long should a service live? Until it is published,
[the roadmap](../../roadmap.md) shows where each lesson stands.
