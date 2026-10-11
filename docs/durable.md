# Durable execution guide

> Status: Phase 6 — **experimental**. Preview API in the optional `durable` extra
> (`pip install "xyberos[durable]"`). Importing a module of the package does not warn; the
> `ExperimentalWarning` is emitted by `warn_experimental` from unstable entry points, and the limits
> below are part of the contract rather than a disclaimer.

Durable execution persists Workflow progress in a SQLite journal, so work survives the process that
was running it. Read the limits first, because they decide whether this is the right tool:

| | |
| --- | --- |
| **Single host** | Workers coordinate through one SQLite journal file. No quorum, no distributed lock, no multi-host ownership. |
| **At-least-once** | A persisted step result proves the step completed, not that its external effect happened exactly once. |
| **One step per claim** | A worker advances one step, then yields. That is what makes a crash boundary always a committed transaction. |
| **No arbitrary checkpointing** | Workflow code is never persisted. A resumed execution is handed its definition again and checked against the record. |

If you need exactly-once effects, safe multi-host execution, or arbitrary Python replay, this is not
that, and the documentation says so wherever a reader might assume otherwise.

## When to use it

Reach for durable execution when all three hold:

- the work is **multi-step**, so a partial result is worth keeping;
- the work **outlives a process** — a restart, a deploy, a crash, or a long wait;
- a step's **side effects are recoverable**: you can either repeat them safely, ask the outside world
  what happened, or accept that the run stops for a human.

Use an in-process [Workflow](./workflow.md) when the work fits in one process and one lifetime, and a
plain `await` when there is nothing to resume.

## The three moving parts

```python
from xyberos.durable import JournalSettings, JournalStore, open_journal
from xyberos.durable.worker import DurableWorker, WorkerSettings

journal = await open_journal(JournalSettings(path="var/journal.db", lease_ttl_seconds=30.0))
store = JournalStore(journal)

handle = await store.submit(
    workflow,                       # any validated xyberos Workflow
    input={"invoice": "INV-1001"},
    timeout=3600.0,                 # optional whole-run budget
    execution_id="invoice-1001",    # optional; a replay with the same work is idempotent
)

worker = DurableWorker(
    store,
    {"invoice:1": workflow},        # the definitions this worker can run
    activities={"charge": ActivityPolicy()},
    settings=WorkerSettings(owner="worker-1"),
)
await worker.serve()                # or run_once() in a test
```

- **`JournalStore`** owns submission, claims, guarded transitions, and read-only inspection. It is
  the only thing that writes.
- **`DurableWorker`** claims work, runs one step, commits the outcome, and lets go. It holds no
  plan in memory, so a crash costs nothing but a claim.
- **`recover(...)`** (also `worker.recover()`) decides what an interrupted attempt means, and is the
  first thing a starting worker does.

## The state machine

Execution states: `PENDING`, `RUNNING`, `RETRYING`, `WAITING`, and the terminals `COMPLETED`,
`FAILED`, `CANCELLED`, `TIMED_OUT`.

| Transition | Meaning |
| --- | --- |
| `PENDING`/`RETRYING` → `RUNNING` | a worker claimed the execution |
| `RUNNING` → `RUNNING` | **recovery**: an expired lease re-claimed under a strictly higher fence |
| `RUNNING` → `PENDING` | **yield**: the worker finished one step and returned the execution to the queue |
| `RUNNING` → `RETRYING` | a failed attempt was rescheduled |
| `RUNNING`/`PENDING`/`RETRYING` → `WAITING` | the execution is parked until something outside the worker acts |

`WAITING` is not claimable by accident: a parked execution is nobody's to take. `RETRYING` is: its
retry becomes claimable when it is due.

Step states: `PENDING`, `RUNNING`, `SUCCEEDED`, `SKIPPED`, `FAILED`, `OUTCOME_UNKNOWN`. The durable
vocabulary is deliberately separate from the in-process engine's `StepStatus`: durable states answer
"what survives a crash", not "what happened during one call".

## What happens after a crash

Recovery reads the journal and decides, in this order:

| The journal says | What happens | Effect repeated? |
| --- | --- | --- |
| no step was running | the execution is ready again; nothing is repeated | no |
| a step succeeded | its **result is reused**; the next step runs | no |
| a step was running, and the step declares `idempotent=True` | the attempt is retried | yes, by declaration |
| a step was running, and the step has a reconciler | the reconciler decides the step's state | only if it says so |
| a step was running, and the step declares neither | the step is `OUTCOME_UNKNOWN` and the execution is parked in `WAITING` | no — nobody guesses |
| the definition is missing or changed | the execution fails as `INCOMPATIBLE_DEFINITION` | no |

This is the failure table from `PLAN.md` section 5.3 expressed as behavior, and it is covered by a
process-kill harness: a real child process dies at each boundary and the parent asserts what the
journal kept.

### Declaring what the executor may do

```python
from xyberos.durable import ActivityPolicy, Reconciliation, StepState

# The effect is safe to repeat: an interrupted attempt is retried.
ActivityPolicy(idempotent=True)

# The effect can be checked with the outside world: it decides what happened.
def reconcile(step_id: str, step_input: object) -> Reconciliation:
    if provider.charge_succeeded(step_input["invoice"]):
        return Reconciliation(state=StepState.SUCCEEDED, output=charge_output(step_input))
    return Reconciliation(state=StepState.PENDING, detail="nothing was charged; safe to retry")

ActivityPolicy(reconcile=reconcile)

# Nothing declared: an interrupted attempt parks the execution. This is the default, and the
# default is deliberately the safe one.
ActivityPolicy()
```

**A reconciler must return the complete output the step would have returned.** Downstream steps
consume it, and the journal accepts a partial output without complaint — so a partial output is
accepted now and fails later in an unrelated step. Build the output with the same function the step
uses; the example does exactly that.

`DurableOutcomeUnknownError` deliberately does not derive from `TransientError`, so a Workflow retry
policy cannot silently repeat an effect of unknown status.

## Cancellation

```python
await store.request_cancellation("invoice-1001", reason="the customer withdrew")
```

The request is persisted before anyone acts on it. Then:

- an execution **nobody owns** is cancelled immediately;
- a **running** execution is cancelled by its owner, which sees the request through a heartbeat and
  cancels the step's cancellation token, so cooperating code stops;
- once a request is persisted, `COMPLETED` **cannot** be recorded. A worker that raced the operator
  does not get to overwrite the request, and a stale worker cannot acknowledge it either.

Cooperation is required: a step that ignores its cancellation token keeps running until it returns.

## Operating the journal

**It is a separate file, and it has to be.** Never point the journal at the application database, and
never at a network filesystem: the locking this design relies on is not dependable there. The
defaults differ from the application provider on purpose — `synchronous="FULL"`, because a committed
transition surviving a crash is the whole point, and process death is not recoverable.

```python
JournalSettings(
    path="var/journal.db",     # a file; an in-memory journal is refused
    lease_ttl_seconds=30.0,
    max_payload_bytes=64 * 1024,
    synchronous="FULL",
)
```

### Backup and restore

- Stop the workers, or accept that a copy taken under load may be missing the last commits.
- Copy the journal **with `journal.db-wal` and `journal.db-shm`**, or run
  `PRAGMA wal_checkpoint(TRUNCATE)` first and copy the single file. A WAL file copied without its
  database is not a backup.
- Restore means replacing the journal while no worker is running. Workers cache nothing, so no other
  state has to be reset — but executions that were `RUNNING` when the copy was taken will be
  recovered from the copy, exactly as they would be after a crash.

### Growth and retention

The journal grows with every step and every event, and it is designed to keep history. Decide
retention per deployment:

- `execution_events` is the fastest-growing table. Keep it if you need incident triage; delete rows
  for executions in a terminal state if you do not.
- `executions`, `execution_steps`, and `worker_leases` are bounded by the number of executions;
  deleting a completed execution cascades to its steps, events, lease, and scheduled retry.
- Deleting terminal executions is the supported way to bound the file, and it destroys the audit
  trail. Do it deliberately, and take a backup first if the history matters.

### Inspection

```python
view = await store.inspect("invoice-1001")
view.status             # ExecutionStatus
view.current_step       # the step a worker is running, if any
view.result             # the persisted result, once completed
view.failure_kind       # why it stopped, if it did
view.steps              # per-step state, attempts, output, error type and message
view.events             # the ordered timeline
view.retry_due_at       # when a scheduled retry becomes claimable

stats = await store.stats()
stats.queued, stats.running, stats.retrying, stats.waiting
stats.completed, stats.failed, stats.cancelled, stats.timed_out
stats.expired_leases    # > 0 means a worker is gone and its work is waiting to be recovered
stats.incompatible      # executions stopped because the definition did not match
stats.oldest_lease_age_seconds
```

`expired_leases` counts only `running` executions a worker abandoned. A ready, retrying, or parked
execution carries a spent lease because the lease row holds the fencing token, and that is not an
orphan.

### Incident triage

| Symptom | Look at | Likely cause |
| --- | --- | --- |
| work is not moving, `expired_leases > 0` | `stats.expired_leases`, then `worker.recover()` | a worker died; recovery was never run, or the lease has not expired yet |
| work is not moving, `expired_leases == 0` | `view.retry_due_at`, `view.current_step` | a retry is not due yet, or a worker is holding the lease |
| `waiting > 0` | `view.steps[].state == OUTCOME_UNKNOWN` | an interrupted attempt needs a decision. Reconcile it, or resume it if you decide to repeat it |
| an execution failed with `incompatible_definition` | `view.version`, the registered fingerprint | the worker does not have the definition the execution was submitted with |
| a step's effect happened twice | `view.steps[].attempts`, `activity_policy` | the step was declared idempotent, or a retry policy covered it. Both are explicit choices |
| `DurableSchemaError` at startup | `journal.version()` | the journal was written by a newer package. Upgrade; do not open it with an older binary |

### Data sensitivity

Step inputs, outputs, and results are stored **verbatim** as JSON, because a resumed execution has to
be replayable from its records alone. The journal therefore holds whatever a step produced.

- Redaction is yours: filter a step's output before returning it.
- `max_payload_bytes` is the only structural guard, and it prevents accidents rather than protecting
  data.
- Events never carry step input, output, or exception messages, so the *event* table is safe to keep
  for longer than the payload columns.
- The failure table's `outcome_unknown` path exists so that an uncertain effect never turns into a
  silent retry. Treat the journal as production data with the same care as the application database.

## Deployment topology

One journal file, one host, any number of worker processes on that host. Two hosts sharing a journal
over a network filesystem is unsupported, and the framework does not detect it for you.

Workers are interchangeable: `WorkerSettings(owner=...)` only labels them for triage. Start workers
with `worker.serve()`, which recovers first, then loops with a bounded backoff, and stop them by
setting an `asyncio.Event`.

## Deliberate limitations

- **No exactly-once effects.** Persisting a result is not proof an external effect was applied once.
- **No multi-host ownership, quorum, or high availability.**
- **No arbitrary Python checkpointing or transparent replay.** Workflow code is not persisted.
- **No parallel steps.** A claim advances one step; the graph rules are the in-process engine's.
- **A required `version` per definition.** Changing a definition in place is refused, so a change
  needs a new version.
- **Polling, not notifications.** An idle worker wakes on its own backoff, bounded by
  `max_poll_interval`.
