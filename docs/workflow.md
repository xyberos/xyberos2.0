# Workflow guide

> Status: Phase 4. The workflow API is preview API and lives in the core package — the `http`,
> `database`, `ollama`, and `durable` extras are not needed and are never imported.

## Three ways to run work

Xyberos keeps the distinction explicit, because the promises differ:

| Mode | Use it for | Guarantees | Does **not** promise |
| --- | --- | --- | --- |
| Direct call (`await direct(...)`) | one function is the whole task | context, deadline, cooperative cancellation; the callable's own exception propagates unchanged | retries, inspection, branching |
| Workflow (`await workflow.run(...)`) | multi-step work you want to inspect, retry, branch, and observe | validated graph, bounded retries, per-step and whole-run deadlines, structured events, no orphan tasks | persistence, recovery, parallel steps |
| Durable execution (`xyberos.durable`) | multi-step work that must outlive the process, on one host | persisted progress, fenced single-owner claims, recovery, cancellation, inspection; **experimental** | exactly-once effects, multi-host ownership, arbitrary Python checkpointing |

An ordinary HTTP handler does not need a workflow. Reach for one when the work is multi-step and
you want the steps to be visible, bounded, and testable without a live provider.

## Defining a workflow

A definition is an immutable value: every builder call returns a new `Workflow`, and nothing is
mutated once validation succeeds.

```python
from xyberos import Backoff, Retry, StepContext, Workflow, seconds


async def classify(value: dict[str, str], context: StepContext) -> dict[str, str]:
    response = await service.call(ticket=value["ticket"])
    return {"ticket": value["ticket"], "category": str(response["category"])}


async def refund(value: dict[str, str], context: StepContext) -> str:
    return f"refund queued for {value['ticket']}"


async def escalate(value: dict[str, str], context: StepContext) -> str:
    return f"escalated {value['ticket']}"


workflow = (
    Workflow("ticket-triage", version="1", input_type=dict)
    .step("classify", classify, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.05)))
    .step("refund", refund, timeout=seconds(5))
    .step("escalate", escalate, timeout=seconds(5))
    .edge("classify", "refund", when=lambda value: value["category"] == "refund")
    .edge("classify", "escalate")
)

result = await workflow.run(input={"ticket": "T-100"}, timeout=seconds(30))
```

| Member | Purpose |
| --- | --- |
| `Workflow(name, version=...)` | the definition; `version` is required data because a durable executor records what it ran |
| `input_type` | optional class (or tuple of classes) checked with `isinstance` before the first step |
| `.step(id, run, retry=, timeout=, metadata=)` | append a step |
| `.edge(source, target, when=)` | connect two steps and carry the source's output to the target |
| `.with_step(...)` / `.with_edge(...)` | append an already-built `Step` or `Edge`, for definitions assembled from data |
| `metadata` | JSON-serializable, secret-free definition data for inspection and later phases |

`Step.timeout` is in seconds and bounds **one attempt**. `Workflow.run(timeout=...)` is the budget
for the whole run. Both are optional; public policies take durations, and the execution context
exposes the absolute deadline they derive.

## Validation

`workflow.validate()` is idempotent and runs automatically before any execution. It never calls a
step function or a branch predicate, so validating and inspecting are free of side effects. A
definition is rejected when:

- the name or version is empty, or the name is not an identifier;
- there are no steps, a step id is empty, or a step id is duplicated;
- a step function is not an `async def`, or accepts fewer than two positional parameters
  (the declared input and the context);
- a step timeout is not greater than zero, or `retry` is not a `Retry` policy;
- an edge names a step that does not exist, duplicates another edge, or is a self-loop;
- a step has more than one edge without a condition, or a conditioned edge is declared *after* that
  unconditioned fallback edge;
- a branch condition is missing, not callable, asynchronous, or does not take one argument;
- the graph contains a cycle (the message names the path), because execution is sequential and
  conditional only;
- an edge is incompatible with the declared types of its endpoints, or entry steps disagree about
  the input they declare and `input_type` does not match them;
- `input_type` is not usable with `isinstance`, or metadata is not JSON-serializable with string
  keys.

Because a definition must be non-empty and acyclic, every step is reachable from an entry step and
can reach an exit step, so no separate reachability rule is needed.

## Execution semantics

Execution is deterministic and sequential. A step becomes ready once every step feeding it has
resolved, and steps are considered in declaration order.

- **Entry steps** (no incoming edge) receive the run's `input`.
- **A reached step** receives the output of the one branch that reached it.
- **A step no branch reached** is *skipped*, is reported as `skipped`, and produces no output.
- **Exactly one edge leaves a step**: the first conditioned edge whose predicate holds, or the
  unconditioned fallback if none does. If a step declares only conditions and none matches, its
  targets are skipped.
- **Two branches reaching one step is a definition bug**: the run fails with a
  `WorkflowExecutionError` naming both sources. Branches that merge must be mutually exclusive.

A step may be a plain async function with its own dependencies closed over, which keeps a
workflow's inputs visible in the definition.

## Retries

```python
Retry(max_attempts=3, retry_on=(TransientError,), backoff=Backoff(initial=0.1, multiplier=2.0, max_delay=5.0, jitter=0.0))
```

`max_attempts` counts the first try, so `max_attempts=1` means no retrying. Classification is
policy driven:

- raise `xyberos.TransientError` (or a subclass) from a step to be retried by the default policy;
- widen or narrow the policy with `retry_on=(...)`, which selects by exception type;
- **a step timeout is not retryable by default** because `StepTimeoutError` is not a
  `TransientError`; retrying a hung operation has to be explicit.
- programming errors (`ValueError`, `KeyError`, …) are never retried silently.

The delay before the attempt *after* attempt `n` is `initial * multiplier ** (n - 1)`, capped at
`max_delay`. `jitter` is the fraction of that delay randomisation may remove, so a delay is never
longer than the computed value and never shorter than `1 - jitter` of it. Jitter draws from the
executor's random source, which tests seed.

Retrying stops immediately on cancellation or when the run's deadline passes, and every attempt
outcome is preserved in order:

```text
RetryExhaustedError: step 'fetch' failed after 3 attempt(s) with RateLimitError
attempts: ['failed', 'failed', 'failed']
cause: RateLimitError
```

A step's side effect may therefore happen more than once. **Idempotency is the caller's
responsibility** for any side-effecting step.

## Timeouts, deadlines, and cancellation

- A step's `timeout` applies per attempt; a retried step gets a fresh budget each time.
- `Workflow.run(timeout=...)` bounds the whole run. It is enforced while a step runs and before the
  next step starts, so a step that overshoots still finishes its work, and the run then fails
  without starting anything new.
- When a step timeout and the run deadline are reached together, the **run deadline wins**.
- Inside a step, `context.remaining()`, `context.expired()`, and `runtime.get_deadline()` expose
  the absolute deadline; `context.check()` raises if cancellation was requested or time is up.

Cancellation is cooperative. Request it with a token:

```python
from xyberos import CancellationToken

token = CancellationToken()
result = await workflow.run(input=data, cancellation=token)
token.cancel("the request was aborted")
```

- A cancellation requested before a step starts prevents that step from starting; the run fails with
  `WorkflowCancelledError` naming that step.
- A cancellation during a step cancels the step's task and cancels the token the step was given, so
  a step that awaits cooperatively observes `asyncio.CancelledError` or the token. A step that
  ignores both keeps running to completion: stopping it is best effort and depends on the step
  cooperating.
- A step can stop the whole run by raising `WorkflowCancelledError` or `WorkflowTimeoutError`.

## Events

Pass `on_event=` a sink to receive structured, sequenced events. Sinks run on the execution path and
must not block.

```text
#1 workflow_started workflow=ticket-triage steps=3
#2 step_started workflow=ticket-triage step=classify attempt=1
#3 step_failed workflow=ticket-triage step=classify attempt=1 duration=0.000000 error=RateLimitError
#4 step_retried workflow=ticket-triage step=classify attempt=1 retrying in 0.05s
#5 step_started workflow=ticket-triage step=classify attempt=2
#6 step_succeeded workflow=ticket-triage step=classify attempt=2 duration=0.000000
#7 step_started workflow=ticket-triage step=refund attempt=1
#8 step_succeeded workflow=ticket-triage step=refund attempt=1 duration=0.000000
#9 step_skipped workflow=ticket-triage step=escalate no branch reached this step
#10 workflow_succeeded workflow=ticket-triage duration=0.050000 outputs=1
```

| Event | Emitted when |
| --- | --- |
| `workflow_started`, `workflow_succeeded`, `workflow_failed`, `workflow_timed_out`, `workflow_cancelled` | the run begins and ends, with its duration |
| `step_started`, `step_succeeded`, `step_failed` | each attempt begins and ends |
| `step_retried` | a failure is retryable and attempts remain |
| `step_skipped` | no branch reached the step |
| `step_timed_out` | the step's own timeout, or the run deadline, stopped the attempt |
| `step_cancelled` | the attempt was started and then cancelled |

Events carry identifiers, status, attempt numbers, durations, timings from the executor's clock,
and the caller's correlation ID. They never carry step input or output, and never exception
messages, because both routinely contain personal or secret data. The raised error and the step's
own logging are where details belong. A step that never started produces no step event; the raised
error and the workflow-level event name it.

## Inspection

`workflow.render()` describes nodes, edges, policies, and definition version without executing
anything, so it is safe in logs, tests, and documentation:

```text
workflow 'ticket-triage' version='1'
  input: dict
  exits: refund, escalate
  step classify  [entry]  run=classify  retry(max_attempts=3, retry_on=(TransientError), backoff(initial=0.05, multiplier=2, max_delay=5, jitter=0))
  step refund  [exit]  run=refund  timeout=5s
  step escalate  [exit]  run=escalate  timeout=5s
  edge classify -> refund when=<lambda>
  edge classify -> escalate
```

A successful run returns a `WorkflowResult`:

- `outputs` maps each exit step that ran to its output; `value` returns the single output and
  raises if the run produced none or several;
- `steps` maps every resolved step id to a `StepOutcome` with its status and every attempt, and
  `outcome(step_id)` returns one of them;
- `duration` is the run's elapsed time on the executor's clock.

A completed run reports every declared step, so `outcome(...)` raises on an unknown id — a caller
mistake. `result.steps.get(step_id)` is the lookup that tolerates absence.

## Errors

| Error | Meaning |
| --- | --- |
| `WorkflowValidationError` | the definition (or a policy, or a `timeout` argument) is invalid; nothing ran |
| `WorkflowExecutionError` | a step failed; `.step`, `.attempts`, and `.outcomes` carry the context, and the original exception is the cause |
| `RetryExhaustedError` | the retry policy used every attempt |
| `StepTimeoutError` | one step attempt exceeded its timeout |
| `WorkflowTimeoutError` | the run exceeded its deadline |
| `WorkflowCancelledError` | cancellation was requested before or during execution |
| `TransientError` | base class a step raises to opt a failure into the default retry classification |

## Testing

The core package ships deterministic doubles, so retries, deadlines, and cancellation are testable
without wall-clock sleeps:

- `ManualClock` — virtual time. `sleep` registers a sleeper instead of waiting, `pending` and
  `sleeps` report what was requested, `advance(delta)` and `advance_to_next()` move time, and
  `wait_for_sleepers(n)` reaches the moment the executor is waiting on a deadline. `drive(task)`
  runs a workflow to completion, moving time whenever nothing else can progress; use
  `wait_for_sleepers`/`advance` whenever a test asserts *exactly* how much time passed.
- `FakeExternalService` + `Reply` — a scripted service covering latency (`Reply.slow`), rate limits
  (`Reply.rate_limited`), transient failures (`Reply.transient`), malformed payloads
  (`Reply.malformed`), and a cancellation-aware call. Replies play in order and the last one
  repeats.
- `pending_tasks()` — assert that no execution left a task behind.

```python
clock = ManualClock()
service = FakeExternalService([Reply.rate_limited(), Reply.ok("done")], clock=clock)
workflow = Workflow("demo").step(
    "fetch", fetch, retry=Retry(max_attempts=3, backoff=Backoff(initial=0.5))
)
task = asyncio.ensure_future(
    workflow.run(executor=WorkflowExecutor(clock=clock, random=Random(1)))
)

result = await clock.drive(task)
assert result.value == "done"   # succeeded on the second attempt
assert clock.sleeps == (0.5,)   # exactly one backoff delay was requested
```

## Deliberate limitations

- **No persistence or recovery.** State is lost when the process exits, and execution events are not
  a durable journal. Durability is the separate [durable executor](./durable.md), which is
  experimental and keeps its own journal.
- **No parallel step execution.** Execution is sequential and conditional; arbitrary DAG scheduling
  is not claimed.
- **No loops.** Cycles are rejected at validation time.
- **Synchronous step functions are rejected.** A blocking or CPU-bound function would stall the
  event loop and could not be cancelled; `await asyncio.to_thread(...)` inside an async step
  instead, accepting that cancellation then cannot stop the thread.
- **No decorator or imperative workflow API.** Definitions stay declarative so they remain
  inspectable; see `PLAN.md` Appendix A.
- **Branches that merge must be mutually exclusive**, and at most one edge leaves a step.
