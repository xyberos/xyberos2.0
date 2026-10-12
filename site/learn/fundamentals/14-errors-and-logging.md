---
title: Handle errors and logging
path: fundamentals
lesson: 14
tier: built-in
status: verified
verify: output
example: examples/learn_fundamentals/fundamentals14_errors.py
prerequisites: ["/learn/fundamentals/08-dependency-injection"]
---

# Lesson 14 — handle errors and logging

## What you will build

Three failures, produced on purpose, and the habit of reading them: every error Xyberos raises derives
from `XyberosError`, and each one names the thing you have to fix rather than the place that noticed
it.

## What you need

The setup from [lesson 1](01-what-is-xyberos.md). This lesson uses nothing beyond the core package.

## The code

<!-- snippet: examples/learn_fundamentals/fundamentals14_errors.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_fundamentals.fundamentals14_errors
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_fundamentals.fundamentals14_errors
    ```

## What it prints

<!-- output: fundamentals14_errors -->
```text
resolving before startup: LifecycleStateError: cannot resolve dependencies while application state is 'new'
a misspelled setting: ConfigurationError: unknown setting(s) at app: unknown
two services that need each other: DependencyCycleError: dependency cycle detected: First -> Second -> First
correlation id in this block: lesson-14
```

## The taxonomy, and when you meet each one

| Error | Raised when | What to do |
| --- | --- | --- |
| `ConfigurationError` | a setting is unknown or cannot be parsed | fix the file or the name; the message names the field and never the value |
| `RegistrationError` | `app.provide` was called with something contradictory | fix the registration, before anything runs |
| `MissingProviderError` | a declared dependency has no provider | register it, or stop declaring it |
| `DependencyCycleError` | two providers need each other | break the cycle with a third contract, or pass one in |
| `ScopeViolationError` | a longer-lived provider needs a shorter-lived one | change one of the scopes ([lesson 9](09-scopes.md)) |
| `DependencyResolutionError` | construction failed | read `error.__cause__`; the framework error is the wrapper |
| `LifecycleStateError` | an operation was attempted in the wrong state | start the application, or stop asking it to work while `new` |
| `HttpError` | a handler wants a status code and a safe message | raise it; the adapter maps it, and never leaks internals |

Two properties are worth more than the table. **The message names the subject**: `dependency cycle
detected: First -> Second -> First` is a description of the fix. And **the runtime refuses early**:
a missing provider is a startup failure, not a first-request failure.

## Logging

The runtime ships helpers rather than a logging configuration, because where logs go is the
application's decision:

| Helper | What it does |
| --- | --- |
| `bind_correlation_id("...")` | binds an id for the duration of a block, so every log line in it is traceable |
| `get_correlation_id()` | reads it back — `lesson-14` above, from the last line of output |
| `bind_context(**values)` | adds diagnostic values, returned by `get_context()` |
| `ContextLogFilter` | attaches the current context to every `LogRecord` as `xyberos_context`, so a formatter can print it |
| `create_task_in_context(...)` | creates a task with the caller's context, including on Python 3.10 |

Attach the filter to your handler and the correlation id appears on every record without being passed
around: `handler.addFilter(ContextLogFilter())`, with a formatter of
`"%(levelname)s %(xyberos_context)s %(message)s"`.

Context is **diagnostic only**. It is not identity and not authorization: a tenant in a context
variable is ambient authority, which is exactly the failure mode
[ADR 0014](../../reference/adr/0014-no-identity-or-authorization-model.md) refuses. Authorization
travels as an argument to a service, never through a context variable.

## Common mistakes

- **Catching `Exception` and logging the message.** Catch the framework error you expect, and let the
  rest propagate — a wiring failure is a startup failure, and swallowing it turns a clear message into
  a confusing one far from its cause.
- **Logging a secret.** Configuration errors deliberately print the field rather than the value; your
  own logging should follow that rule, which is what `LoggingPolicy.metadata_only()` in `xyberos.ai`
  enforces for prompt and completion content.
- **Using context for authorization.** See above: it is a diagnostic channel, and treating it as
  authority is how one request reads another tenant's rows.

## Exercise

Add a fourth failure to the module: a service whose factory returns the wrong type.

<details>
<summary>Show the answer</summary>

Registering `app.provide(Contract, factory=lambda: object())` fails at *registration* with
`RegistrationError`, naming both what the factory returns and the contract it was registered against —
before anything runs.

That is the pattern to learn from this lesson: the earlier a mistake can be caught, the more useful the
message. Registration catches the shape, `validate()` catches the graph, startup catches construction,
and a request catches only what is left.
</details>

## Next

That is the Fundamentals path. [The roadmap](../../roadmap.md) shows the lessons still in progress and
what comes after them — the traditional path, which builds a database-backed application from this
same starting point.
