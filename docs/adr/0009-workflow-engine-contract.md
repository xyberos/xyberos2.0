# ADR 0009: Freeze the workflow engine contract

**Status:** accepted

## Context

Phase 4 ships the first stable multi-step execution contract. It has to be inspectable and testable
without a live provider, deterministic about retries and time, safe to cancel, and honest about what
it does not promise. It must also be reusable by the optional AI facade without being shaped by it,
must not import HTTP, database, AI, or durable modules, and must not promise durability.

## Decision

**Definitions are immutable values.** Every builder call returns a new `Workflow`; `metadata` is
stored as a frozen mapping, copied away from the caller. Validation is memoised per instance and a
derived definition starts unvalidated again, so editing a validated workflow cannot skip validation
of the new part.

**Validation is the only rejection point, and it is side-effect free.** It is decidable from the
definition alone and never calls a step function or a branch predicate. It rejects identity
problems, duplicate or empty step ids, non-async step functions and wrong arity, non-positive step
timeouts, policies of the wrong shape, edges that name unknown steps, duplicate edges, self-loops,
more than one unconditioned edge per source, a conditioned edge declared after the fallback,
conditions that are missing, non-callable, asynchronous or of the wrong arity, cycles (reported with
their path), incompatible declared input/output types, an `input_type` that is not usable with
`isinstance`, and metadata that is not JSON-serializable with string keys. Because a definition must
be non-empty and acyclic, reachability of every step from an entry and to an exit follows, so no
separate rule is needed.

**Steps are `async def step(value, context)`.** Synchronous step functions are rejected at
validation time rather than run inline: blocking or CPU-bound code would stall the event loop and
could not be cancelled. `asyncio.to_thread(...)` inside an async step is the documented answer, and
a real step-executor boundary with cancellation is deferred to the backlog rather than implemented
by force-terminating threads.

**Execution is sequential and conditional only.** A step becomes ready once every step feeding it
has resolved and is considered in declaration order. Entry steps receive the run input; a reached
step receives the output of the one branch that reached it; a step no branch reached is *skipped*.
Exactly one edge leaves a step: the first conditioned edge whose predicate holds, otherwise the
unconditioned fallback that must be declared last. Two taken branches reaching one step is a
definition bug and fails at runtime with both sources named.

**Time reuse the runtime's context helpers.** Steps execute inside `bind_context`,
`bind_deadline`, and `create_task_in_context`, so correlation IDs, logger bindings, and the absolute
monotonic deadline reach a step through the same mechanism the rest of the runtime uses. The engine
introduces no second propagation mechanism and no new dependency.

**The executor owns every task it creates.** Each attempt is a task raced against its stop
conditions and always awaited or cancelled before the executor returns, so no execution outlives the
call. The per-attempt cancellation token is a *child* of the run token, which is what lets one
attempt time out and be retried without cancelling the run.

**Retries are bounded and policy driven.** `max_attempts` counts the first try. Classification comes
from `retry_on`, defaulting to `(TransientError,)`, so only failures that opt in are retried; a step
timeout is deliberately not retryable by default, and programming errors are never retried. Backoff
delays are computed from an injected clock and an injected random source. Retrying stops immediately
on cancellation or deadline expiry, and every attempt outcome is preserved in order on the raised
error.

**Public policies take durations; the context exposes the deadline.** `Step.timeout` bounds one
attempt, `Workflow.run(timeout=...)` bounds the run, and the derived absolute deadline is what
`StepContext.remaining()`, `StepContext.expired()`, and `runtime.get_deadline()` report. The run
deadline is enforced while a step runs and before the next step starts, and it wins when a step
timeout and the deadline are reached together.

**Cancellation is cooperative and documented as such.** A token cancelled before a step prevents that
step from starting and names it in the error. During a step, the attempt task is cancelled and the
attempt token is cancelled, so cooperating code observes it. A step that ignores both keeps running:
stopping it is best effort. A step may stop the whole run by raising `WorkflowCancelledError` or
`WorkflowTimeoutError`. Because these errors are raised from step code, their `workflow` context is
optional and the executor supplies its own context when it re-raises.

**Events are structured, sequenced, and payload-free.** Events carry identifiers, status, attempt
numbers, durations, timings from the executor's clock, and the caller's correlation ID. They never
carry step input or output, and never exception messages, because both routinely contain personal or
secret data.

**Inspection and test doubles ship with the engine.** `Workflow.render()` describes nodes, edges,
policies, and version without executing anything. `xyberos.execution.testing` provides
`ManualClock`, `FakeExternalService`, `Reply`, `pending_tasks`, and the `drive` virtual-time driver,
so retries, deadlines, and cancellation are testable without wall-clock sleeps. The fake external
service is deliberately not an AI provider; Phase 5 adds its own fake model provider.

**The engine makes no durability, parallelism, or loop promise.** State is lost when the process
exits, events are not a journal, cycles are rejected, and there is no declared DAG parallelism.

## Consequences

- Phase 6 consumes this definition format and must version it; definition versioning is already
  recorded as Phase 6's responsibility in [ADR 0003](0003-versions-and-experimental-scope.md).
- Phase 5 may import workflow error, deadline, cancellation, and event types, but must not introduce
  AI concepts into `xyberos.execution` or let a provider shape the engine. Phase 5 owns its own fake
  model provider.
- `input_type` is validated and checked with `isinstance`, so `dict[str, int]` is rejected and a
  richer input contract would need a new ADR.
- `Step.timeout` is a scalar in seconds rather than a policy object, because it has exactly one
  knob; a timeout policy object would need a new ADR. This is a deliberate simplification of the
  plan's "timeout policy" wording.
- Ambiguous merges fail at runtime rather than being statically rejected, because exclusivity is not
  decidable for arbitrary conditions; a static analysis would need a new ADR.
- A blocking step joined through `asyncio.to_thread` cannot be cancelled, and a real step-executor
  boundary that could is in the deferred backlog.
- The public error messages name exception types and never echo payload; review of message safety is
  part of the per-phase delivery cadence.
