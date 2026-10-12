---
title: Failures, timeouts, and retries
path: ai
lesson: 6
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai06_errors.py
prerequisites: ["/learn/ai/03-first-call"]
---

# Lesson 6 — failures, timeouts, and retries

## What you will build

The failure half of every model call. A model service is a remote system that is slow, rate-limited, and
occasionally wrong, so this lesson is about the taxonomy the runtime already has and the retry policy
that belongs on top of it.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai06_errors.py -->

The step is a workflow step, and that is deliberate: a model call inside the execution engine inherits a
retry policy, a deadline, and cancellation handling without any of them being written by hand. The
engine also refuses a *synchronous* step function, because blocking work cannot be cancelled:

```text
WorkflowValidationError: step 'ask' must be an async function: blocking or CPU-bound work would stall
the event loop and could not be cancelled; await asyncio.to_thread(...) inside an async step instead
```

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai06_errors
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai06_errors
    ```

## What it prints

<!-- output: ai06_errors -->
```text
after a transient failure: Answered on attempt 2. (calls: 2)
a timeout:    AITimeoutError | transient: True
a refusal:    AIRefusalError | transient: False
rate limited: AIRateLimitError | transient: True
```

| Failure | Class | Transient? | What to do |
| ------- | ----- | ---------- | ---------- |
| slow or unreachable service | `AITransportError` | yes | retry with backoff |
| no answer inside the deadline | `AITimeoutError` | yes | retry, with a shorter prompt or a longer budget |
| rate limited | `AIRateLimitError` | yes | retry, and slow down |
| unparseable payload | `AIInvalidPayloadError` | yes | retry: the next answer may be well-formed |
| model refused the request | `AIRefusalError` | **no** | do not retry; change the prompt or escalate |
| capability not declared | `AIUnsupportedCapabilityError` | **no** | fix the configuration |
| model not found | `AIModelNotFoundError` | **no** | fix the configuration |
| payload fails the schema | `AISchemaError` | no | retry only with a changed prompt |

Transience is a property of the *error class*, not of the exception message: the engine's retry policy
asks `isinstance(error, TransientError)`, which is why the lesson prints that boolean rather than a
guess. The first line is the payoff — a transient failure plus `Retry(max_attempts=2)` becomes an answer
on the second call, with `calls: 2` proving the retry happened.

## Common mistakes

- **Retrying a refusal.** It costs tokens and produces the same refusal; a refusal is a prompt or policy
  problem, and the fix is upstream of the retry.
- **Retrying without a bound.** A model service under load plus an unbounded retry loop is a
  denial-of-service you wrote yourself; `max_attempts` is not optional.
- **Retrying a non-idempotent effect.** Retry the *call*, never the side effect — send nothing, write
  nothing, then retry. The approval boundary in the hybrid path exists for this reason.
- **Catching `AIError` and returning a default.** A silent default hides a class of failure the caller
  could have handled; let it out, and let the error policy decide what a client sees.
- **Doing slow work in a synchronous step.** The engine's validation catches it, and the error message
  says where to put the blocking call.

## Next

Lesson 7 starts the half of the path the runtime does not provide: conversation history, memory, and the
retrieval layer you build yourself.
