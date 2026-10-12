---
title: Write your first test
path: fundamentals
lesson: 13
tier: built-in
status: verified
verify: pytest
example: examples/learn_fundamentals/fundamentals13_first_test.py
prerequisites: ["/learn/fundamentals/08-dependency-injection"]
---

# Lesson 13 — write your first test

## What you will build

A test file for the application you have been building, and the habit that makes it worth having: **a
test double must satisfy the contract**.

There is no Xyberos test runner and no plugin to install. A test is an ordinary pytest test; what the
framework ships is the doubles that make it fast.

## What you need

pytest, and the `http` extra, because two of these tests make a request:

=== "PowerShell"

    ```powershell
    python -m pip install pytest "xyberos[http]"
    ```

=== "POSIX"

    ```bash
    python -m pip install pytest 'xyberos[http]'
    ```

## The code

This lesson *is* the test file. Copy it into your project as `tests/test_app.py`:

<!-- snippet: examples/learn_fundamentals/fundamentals13_first_test.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m pytest examples/learn_fundamentals/fundamentals13_first_test.py -q
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m pytest examples/learn_fundamentals/fundamentals13_first_test.py -q
    ```

Four tests, and they get faster as they get further from HTTP: a plain unit test, a request through
the test client, a request with a dependency replaced, and a check that the application validates and
starts.

## The habits worth copying

| Habit | Why |
| --- | --- |
| Write the application against a `Protocol`, not a class | the contract is what a caller needs, so a double can satisfy it |
| Use `create_test_client(...)` as a context manager | entering it runs the lifespan, which validates and starts the application |
| Override the contract with `app.with_overrides({...})` | each test gets its own application, so nothing leaks between tests |
| Write `asyncio.run(scenario())` inside a sync test | no `pytest-asyncio` marker and no plugin: each test gets its own event loop, which is what an `App` requires anyway |
| Never sleep | inject a clock and move it, rather than waiting for time to pass |

The double must satisfy the contract. Override a class contract with something that is not an instance
of it, and the failure arrives when the service is first resolved — lesson 8's second line of output is
the same class of mistake caught at composition time.

## Common mistakes

- **A request outside the client's context manager.** It is refused with a `500`, because the
  application has not started. If every request fails in a test, check the `with` block first.
- **A double that does not satisfy the contract.** The provider is checked, and you get
  `DependencyResolutionError` naming what the provider returned instead of what the contract wanted.
- **Testing through the HTTP layer only.** The cheapest test in the file touches no application at
  all, and it is the one that runs in a millisecond.

## Exercise

Write a test that fails because the application is wired incorrectly, then fix the wiring.

<details>
<summary>Show the answer</summary>

The answer is one test: compose an `App`, register a service whose own dependencies are missing, and
expect `validate()` to raise `MissingProviderError`.

You have already seen that failure produced by a module you ran — it is the second line of
[lesson 8](08-dependency-injection.md)'s output, and the page there documents the message:

```text
no provider is registered for Repository; required by UserService
```

`MissingProviderError` names both the missing piece and the service that needed it, which is usually
enough to fix the wiring without debugging.
</details>

## Next

Lesson 14 covers the errors you will meet, and how to read them. Until it is published,
[the roadmap](../../roadmap.md) shows where each lesson stands.
