# Ticket triage workflow

An inspectable, in-process workflow with retries, a conditional branch, per-step timeouts, and a
run budget. The external service is a scripted fake, so the example is deterministic and needs no
network.

```powershell
cd examples
python -m workflow.app
```

## What it demonstrates

- **A definition is a value.** `build_workflow` returns an immutable `Workflow` you can validate
  and `render()` before anything runs.
- **Explicit input and output.** Each step is `async def step(value, context)`, receives only its
  declared input plus the execution context, and returns the value the next step receives.
- **Branching by edge conditions.** `classify -> refund` carries a predicate and
  `classify -> escalate` is the fallback, so exactly one branch runs. The step that is not selected
  is reported as `skipped`, not as a failure.
- **Merging.** Both branches feed `notify`, which receives the output of the branch that reached
  it.
- **Policy-driven retries.** `classify` retries a rate-limited call because a rate limit is a
  transient failure; a malformed response would not be retried without an explicit policy.
- **Bounded time.** Each step has its own timeout and the whole run has a budget that no step may
  exceed.
- **Structured events.** The `on_event` sink receives sequenced `WorkflowEvent` values that carry
  identifiers, attempts, durations, and timings, and never carry step input or output.

## Where to go next

- `docs/workflow.md` explains the contract, the three execution modes, and the operational
  limits.
- `tests/workflow/` contains the deterministic exit-gate tests, including the `ManualClock` and
  `FakeExternalService` doubles used here.
