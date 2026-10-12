---
title: Performance and concurrency
status: verified
---

# Performance and concurrency

There is one performance question this framework has an opinion about, and it is the one every SQLite
deployment meets: **what happens when more than one writer wants the file at the same time.** The
answer is a bounded retry budget, and the point of the budget is that the failure is *bounded* — a
request that cannot be served is refused in a known way rather than waiting forever.

## Why this page prints counts instead of milliseconds

The baseline numbers for this repository live in
[the performance baselines](../reference/performance.md): one writer at roughly two thousand writes per
second, twenty contended writers at roughly 170, both measured by `python -m pytest -s tests/perf` on
one machine. They are recorded rather than asserted here because a duration is a property of the machine
it ran on, and a documentation page that prints one is measuring the reader's laptop, not the framework.

So the transcript below counts what happened. Every number in it is reproducible on any machine, which
is the only kind of claim an output block can make.

## Twenty writers, one row

<!-- snippet: examples/learn_production/performance01_contention.py -->

<!-- output: performance01_contention -->
```text
writers that committed: 20 of 20
refusals: none
the row every writer touched: 20.0
with the lock held: TransientDatabaseError - the database stayed locked after 1 attempt(s)
after three attempts: TransientDatabaseError - the database stayed locked after 3 attempt(s)
```

Four things are worth reading out of those five lines:

- **`20 of 20`, and the row is `20.0`.** Every writer's increment landed exactly once. Retrying is safe
  here because the *operation* is idempotent in the sense that matters: the retry re-runs the whole
  transaction, and the transaction's own read-modify-write is atomic in the database rather than in the
  application. A retry that re-ran only the second half of a two-step write would double it.
- **`refusals: none` under the default budget.** The default is five attempts with a 50 ms base delay
  and a 5 s busy timeout, which is enough for twenty short writers to serialize through one lock without
  any of them giving up.
- **`after 1 attempt(s)` versus `after 3 attempt(s)`.** A held lock produces the *same* error with a
  different count: the budget decides how long the caller waits before it is refused, and nothing else.
  Refusal, not a hang, is the contract.
- **The lock is held on purpose.** The module holds a write transaction open for the second half so the
  contention is *certain* rather than probable — which is also the honest way to test this behaviour in
  your own suite.

## The settings, and what each one does

| Setting | Default | What it decides |
| ------- | ------- | --------------- |
| `journal_mode` | `WAL` | readers proceed while a write is in flight; there is still exactly one writer at a time |
| `synchronous` | `NORMAL` | speed versus durability across an **operating-system** crash. `FULL` when a committed transaction must survive one |
| `busy_timeout_ms` | `5000` | how long SQLite itself waits for the lock before reporting `database is locked` to the driver |
| `retry_attempts` | `5` | how many times `retrying` re-runs the operation after lock contention, in total |
| `retry_base_delay` | `0.05` | the sleep between attempts; the delay grows linearly, so the budget is bounded in time as well as in count |
| `foreign_keys` | `True` | enforced per connection |
| `echo` | `False` | SQL statement echo, for a debugging session rather than a deployment |

The two timeouts are easy to confuse, and they are not the same mechanism: `busy_timeout_ms` is SQLite
waiting *inside* one attempt, `retry_attempts × retry_base_delay` is the application waiting *between*
attempts. A very large busy timeout makes the retry budget redundant; a very small one makes the budget
do all of the work, which is what the transcript's second half demonstrates on purpose.

## Retrying is a policy about operations, not about connections

`retrying(operation, *, attempts=None, base_delay=None)` takes a callable that receives a connection,
opens a transaction around it, and re-runs the *whole* callable on contention. Three consequences:

1. **Only lock contention is retried.** Anything else propagates unchanged, so a bug in the operation is
   never repeated five times with a delay between the attempts.
2. **The operation must be idempotent.** Retrying a write that already committed is a correctness bug
   rather than a performance one; make the write a single statement or make it re-runnable.
3. **The budget is per call.** A caller that knows better can pass `attempts=1` to refuse immediately,
   which is how the transcript's held-lock half stays deterministic.

[The database reference](../reference/database.md#concurrency-and-the-retry-policy) has the policy's
rules in full, including which driver errors count as contention.

## Concurrency beyond the database

| Where concurrency shows up | What the runtime does | What to watch |
| -------------------------- | --------------------- | ------------- |
| request handling | one task per request; app-scoped providers are constructed once under a lock | a slow *factory* serialises startup, not requests |
| app scope | resolved once, then shared between every request | shared mutable state is yours to protect |
| request scope | created per request, released at the end of it | it is the right home for a per-request connection or principal |
| transient scope | a new instance per injection | anything with a `close`/`aclose` is refused, so nothing leaks silently |
| blocked calls | `asyncio.to_thread` and executors are yours to choose | a `run_in_executor` call loses the diagnostic context unless you use `capture_context_runner` ([observability](observability.md)) |
| shutdown | drains in-flight request contexts, then closes in reverse | with `app.shutdown_timeout = None` the drain is unbounded ([internals](internals.md)) |

## Where the framework's cost actually is

Three structural facts, all of them design decisions rather than accidents:

- **Route compilation is cached.** The adapter compiles routes once and rebuilds only when the route
  version changes, so the per-request work is middleware, resolution, and response conversion.
- **Resolution is cached per scope.** An app-scoped provider is constructed once; a request-scoped one is
  memoized for the request, so two handlers asking for the same contract in one request share an
  instance.
- **The framework adds no I/O.** There is no metrics loop, no background task, no automatic network call
  anywhere in the runtime. Anything asleep inside your process was started by your code.

## Common mistakes

- **Raising concurrency to raise write throughput.** Under SQLite the retry backoff sets the pace, so
  more writers make the wait longer, not the work faster. Batch the writes into one transaction instead.
- **Treating `busy_timeout_ms` as the retry policy.** It is one attempt's patience; the budget is what
  turns contention into a refusal rather than a slow request.
- **Retrying an operation that is not idempotent.** The retry re-runs the callable, not the part after
  the failure.
- **Tuning `synchronous` for speed without deciding about durability.** `NORMAL` under WAL is the
  documented trade: a crash of the *process* is safe, a crash of the *operating system* can lose the most
  recent commit.
- **Putting the durable journal in the application's database file.** The durable contract's limits are
  single-host and one journal file, and [the durable reference](../reference/durable.md) says to keep the
  application database and the journal in separate files.
