# Performance baselines

> Status: Phase 7. These numbers exist so a change of *kind* is visible. They are not targets, not
> promises, and not a benchmark against other frameworks.

## How to run it

```powershell
python -m pytest -s tests/perf
```

`-s` matters: a passing test's output is captured, so without it you get "6 passed" and no table. The
suite runs in about a second because the scenarios are small on purpose — a baseline that takes
minutes is a baseline nobody runs.

## What is measured, and what each number includes

| Baseline | Includes | Excludes |
| --- | --- | --- |
| Compose and validate 50 providers | `App()` construction, 50 registrations, the full graph and annotation validation | constructing any service |
| Start and stop 50 eager providers | `validate()`, constructing 50 app-scoped services, closing them in reverse order | request handling |
| Route round trip, in process | the whole ASGI path: middleware, request scope, handler injection, response conversion, **and the Starlette test client** | the network, TLS, and the server |
| Workflow of 20 steps | definition execution, per-step context, events, result assembly — reported per step | any real work inside a step |
| SQLite, 20 concurrent writers | 20 transactions contending for the single writer, with the bounded retry policy | the schema setup, which is done before timing |
| Durable journal | submitting 20 executions *and* running each to completion: a claim, a step commit, and a terminal transition per execution | recovery, which is covered by the process-kill harness |

The route measurement is deliberately honest about the test client: it is the largest single
component of that number, and reporting the framework's share separately would mean measuring
something no user experiences.

## Capacity: where the wall is

Three of the numbers above decide almost every capacity question, and one of them is counter-intuitive
enough to be worth stating explicitly.

| Scenario | best | median | p95 |
| --- | --- | --- | --- |
| SQLite, one write per transaction (`synchronous=NORMAL`, WAL) | 0.32 ms | 0.47 ms | 0.62 ms |
| SQLite, 20 concurrent writers with the retry policy | — | 120 ms for all 20 | — |

**One writer, no contention: about 2 000 writes per second.** The reciprocal of 0.47 ms is the ceiling
a single writer approaches, so a workload that fits in tens of millions of rows on one box is not
limited by the framework. Reads are never blocked under WAL, so read volume is a different question.

**Under contention, the retry backoff — not the disk — sets the pace.** Twenty concurrent writers take
120 ms in total, which is about 170 writes per second: an order of magnitude *below* the sequential
figure, on hardware that has no trouble writing. The reason is in
[the retry policy](./database.md#concurrency-and-the-retry-policy): a contended writer waits
`base_delay` (10 ms in the baseline) before retrying, and twenty writers serialising through one lock
spend most of their time sleeping rather than writing. Two consequences follow, and both are design
guidance rather than tuning advice:

- **Contention is a design smell, not a throughput lever.** Batch writes into one transaction, or
  serialise them through one writer, rather than raising concurrency and hoping.
- **`base_delay` trades latency for aggregate throughput.** A smaller backoff recovers throughput under
  contention at the cost of more failed lock attempts; the default is chosen to keep retries cheap and
  bounded, not to maximise throughput.

**What this means for a decision.** If your write volume fits one box's single writer — thousands of
writes per second, if writes are batched — SQLite is enough and the framework is not your bottleneck.
If it does not, the engine is the limit and the answer is a different provider
([writing a database provider](./database-providers.md)), not a faster runtime. That boundary is stated
for adopters in [where Xyberos fits](./positioning.md).

## The recorded baseline

Taken 2026-10-11 on Windows 11 (CPython 3.12.10, local NVMe), one run of the suite. Treat these as
"the same command on the same machine last time", nothing more.

| Scenario | best | median | p95 |
| --- | --- | --- | --- |
| Compose + validate 50 providers | 1.82 ms | 2.76 ms | 4.17 ms |
| Start + stop 50 eager providers | 1.96 ms | 2.88 ms | 4.05 ms |
| Route round trip, in process (100×, test client included) | 0.33 ms | 0.49 ms | 0.80 ms |
| Workflow of 20 steps | 1.28 ms | 1.32 ms | 3.11 ms |
| — per step within that workflow | — | 0.07 ms | — |
| SQLite, 20 concurrent writers | — | 101.8 ms | — |
| Journal, 20 executions submitted and run | — | 11.5 ms | — |

Two readings are worth taking from the table rather than the exact numbers:

- **Composition is cheap and does not grow alarmingly.** Fifty providers validate in single-digit
  milliseconds, which is the reason the framework can afford to validate eagerly instead of
  inventing a lazy path.
- **Contention, not the framework, is the expensive part.** Twenty concurrent writers cost about as
  much as seven hundred route round trips. That is SQLite being SQLite — one writer at a time — and
  it is why the database guide says to keep write transactions short and away from network calls.
  The retry policy bounds how long that contention lasts; it does not make it free.

## The ceilings, and why they are loose

`tests/perf/test_baselines.py` asserts a ceiling per scenario, each roughly an order of magnitude
above the recorded baseline (2 s for composition, 250 ms for a request, 50 ms per workflow step,
20 s for twenty contended writes, 500 ms per durable execution). The reason is the same one the plan
states: a regression signal, not an optimization target. A threshold tight enough to be interesting
on a laptop fails on a shared CI runner for reasons that have nothing to do with the change, and a
test that fails for unrelated reasons gets ignored — which is worse than no test.

So: if a ceiling fails, reproduce it with `-s` twice, compare the table against this one, and treat a
ratio above roughly 3× as worth investigating before assuming the machine was busy.

## What has not been done

Nothing here has been optimized, and nothing will be without a number that says it matters. In
particular:

- **No caching of anything.** Settings, provider plans, and route compilation are computed once per
  application, which is why startup is already flat.
- **No connection pooling beyond the SQLAlchemy engine default.** SQLite's single writer makes
  pooling a contention question rather than a throughput question, and the engine is created once per
  application and closed on shutdown.
- **No benchmarking of the AI facade against a live provider.** A model's latency is the number that
  matters there and it is not this project's to measure; the fake provider is what keeps those tests
  fast.
- **No memory measurement.** Resident memory is the one resource a Python framework rarely controls
  from its own code, and the bounded things that do matter — payload limits, retention, the journal
  file — are documented as limits instead ([durable operation](./durable.md#growth-and-retention)).

If you need a number this page does not have, add a scenario to the suite rather than a claim to the
docs: the harness is small, and a baseline nobody can re-run is a story.
