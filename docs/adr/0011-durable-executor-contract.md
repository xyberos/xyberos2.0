# ADR 0011: Freeze the durable executor contract

**Status:** accepted

## Context

Phase 6 adds persisted Workflow progress. It is the highest-risk subsystem in the architecture
because its guarantees are about what happens *after* a crash, and because the honest answer is
usually weaker than a reader expects: at-least-once, single host, no exactly-once external effects.
The plan requires a formal transition table and a schema before any worker exists, and it requires
the experimental boundary to be visible in the API rather than only in prose.

Two constraints shaped the design. First, the runtime must stay thin: durable execution is optional
and must not pull an SDK into core. Second, SQLite is the only storage, so the guarantees have to be
the ones a single write lock can actually provide.

## Decision

**Scope is one host and one journal file, and the limits are part of the contract.** Workers
coordinate through SQLite transactions and fencing tokens. There is no quorum, no distributed lock,
no multi-host ownership, and no arbitrary Python checkpointing. Exactly-once external effects are
explicitly *not* promised: a persisted step result proves a step completed, not that its remote
effect happened once.

**The journal is a separate file with its own schema, reusing the database extra's plumbing.** It
shares `SqliteSettings`-based connection handling with the application database provider — PRAGMAs,
WAL, the bounded busy timeout, and the retry-on-contention helper — but never shares a file, a
provider instance, or a table. Journal statements live in `xyberos/durable/journal.py`, and the
default is `synchronous="FULL"` rather than the application database's `NORMAL`, because a
committed transition surviving a crash is the entire point.

**Schema versioning is embedded and forward-only.** The schema is versioned DDL applied in one
transaction, with the version recorded in `journal_metadata`. Opening a journal written by a *newer*
package raises `DurableSchemaError` instead of interpreting rows this package does not understand.
The durable extra deliberately does not depend on a migration engine to open itself; a future schema
version appends a step to `_MIGRATIONS`.

**The transition table is the contract, and it is validated before any write.** Execution states are
`PENDING`, `RUNNING`, `RETRYING`, `WAITING`, and the terminals `COMPLETED`, `FAILED`, `CANCELLED`,
`TIMED_OUT`. Step states are `PENDING`, `RUNNING`, `SUCCEEDED`, `SKIPPED`, `FAILED`,
`OUTCOME_UNKNOWN`. Two transitions carry meaning worth stating: `RUNNING -> RUNNING` is *recovery*
(an expired lease re-claimed under a strictly higher fence), and `RUNNING -> PENDING` is a *yield*
(the worker finished one step and returned the execution to the ready queue). `RETRYING` means a
scheduled retry will be claimed automatically; `WAITING` means the execution is parked until
something outside the worker acts, so no claim is eligible.

**Ready work belongs to nobody.** A claim requires `PENDING`/`RETRYING` with any retry due, or a
`RUNNING` execution whose lease has expired. A live lease protects `RUNNING` work only, which is
what lets a worker advance one step per claim and yield without waiting for a lease to expire. A
claim is one conditional `UPDATE` (re-stating every eligibility condition) plus a lease upsert that
increments a monotonic fencing token, so two workers racing the same row cannot both win.

**Every write is guarded by ownership and the fencing token.** Step transitions, retries,
cancellation acknowledgements, and terminal transitions all carry `owner`, `fence`, and a live-lease
condition in their `WHERE` clause. A refused write is re-read and reported as a lease problem, a
cancellation, or a state problem — never as "no rows matched" — so a worker that lost its lease
learns why instead of retrying blindly.

**Deadlines and leases are wall-clock and persisted.** The in-process engine uses a monotonic clock,
which cannot survive a restart, so durable deadlines are stored as UTC timestamps and every row is
stamped from an injectable `WallClock`. A retry scheduled at or after the deadline is never
scheduled: the execution is recorded as `TIMED_OUT`, because a retry nobody can run is not a retry.

**Cancellation is request-first, and cancellation wins.** A request is persisted (column plus event)
before anyone acts on it. An owner records `CANCELLED` under its fence; an execution nobody owns is
cancelled immediately. Once a request is persisted, `COMPLETED` cannot be recorded — a worker that
raced the operator does not get to overwrite the request — and a stale worker cannot acknowledge it
either.

**An uncertain outcome is never guessed.** A step interrupted after it may have produced its effect
is recorded as `OUTCOME_UNKNOWN` and the execution is parked in `WAITING`. Retrying it requires an
activity policy that declares the step idempotent or supplies a reconciler; with neither, the
execution waits for a decision. `DurableOutcomeUnknownError` deliberately does not derive from
`TransientError`, so a workflow retry policy cannot silently repeat an effect of unknown status.

**Payloads are JSON, bounded, and stored verbatim.** Inputs, step outputs, and results must be
JSON-serializable and within `max_payload_bytes`; otherwise submission or the write fails with
`DurablePayloadError`. The journal never logs payload content. Redaction is the application's job —
it filters a step's output before persisting it — and data sensitivity, retention, and backup are
documented operator responsibilities rather than hidden defaults.

**The experimental boundary is visible.** `ExperimentalWarning` is emitted from unstable entry
points, the package docstring, guide, and package metadata state the single-host and at-least-once
limits, and the limits are repeated wherever a reader might assume more.

**A parked execution is not claimable, and an unresolved attempt is never handed out as work.**
`WAITING` is reachable from `RUNNING`, `PENDING`, and `RETRYING`, but no claim is eligible for it, so
a parked execution waits for a person rather than for a worker. The scheduler reports
``NEEDS_DECISION`` for a step in ``OUTCOME_UNKNOWN`` instead of treating it as ready, which closes the
one dangerous window this design has: if an operator resumes a parked execution *before* reconciling
it, the next worker parks it again with a reason instead of silently repeating an effect nobody can
observe.

**Events are appended, never rewritten.** Every decision recovery makes becomes an event, so an
operator can reconstruct why an execution resumed, retried, parked, or stopped without reading a
log line written by a process that no longer exists.

## Consequences

- Phase 7 re-audits the labelling and decides promotion; promoting durable execution would require
  demonstrating the backup/restore and resource-bound evidence listed in `PLAN.md` section 5.4.
- SQLite write locks are the only coordination, so a journal on a network filesystem is unsupported:
  the locking it relies on is not dependable there. Deployment topology is documented, not enforced.
- One step per claim costs a claim, a lease upsert, and two events per step. That is the price of a
  crash boundary that is always a committed transaction.
- `xyberos.durable` imports `xyberos.database.sqlite` for connection plumbing, so it requires the
  packages the `durable` extra declares, and it must never import `xyberos.http`, `xyberos.ai`, or an
  AI SDK — a boundary the import tests assert.
- Workflow code is never persisted. Resuming requires the caller to supply the definition again and
  the fingerprint to match, otherwise the execution is failed as an incompatible definition.
- Step outputs are stored verbatim, so the operator owns data sensitivity and retention; the size
  limit is the only structural guard, and richer redaction would need its own decision.
- The in-process engine and the durable executor keep separate status vocabularies
  (`StepStatus` versus `StepState`) on purpose: they answer different questions, and one must not be
  read as the other.
- **A reconciler must return the whole step output**, not the part it happens to know. Downstream
  steps consume it, and the journal accepts a partial value without complaint, so a partial output
  is accepted now and fails later inside an unrelated step. `examples/durable_workflow` builds the
  output with the same function the step uses, which is the pattern to copy; a stricter check would
  need its own decision because only the definition knows the output's shape.
- **A spent lease outlives its claim**, because the lease row carries the monotonic fencing token, so
  `expired_leases()` and the `expired_leases` statistic count only `running` executions. Deleting the
  row on release would reset the token and break fencing, so the alternative — a nullable
  "abandoned" marker — was rejected as more state for less safety.
- **The experimental warning is emitted once per process per entry point.** `open_journal` and
  `DurableWorker` both warn, which is what the exit criterion asks for, and the deduplication keeps a
  long-lived application from repeating the same paragraph on every worker it starts.
- **The process-kill harness deliberately does not share the parent's virtual clock**: a killed
  subprocess cannot be given one. `xyberos.durable.testing.expire_leases` backdates a lease instead of
  sleeping, which is deterministic and equivalent to time passing with no heartbeat.
