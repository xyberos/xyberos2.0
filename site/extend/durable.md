---
title: Multi-step work that outlives the process (experimental)
status: verified
---

# Multi-step work that outlives the process (experimental)

**Tier: experimental.** `xyberos.durable` is the one surface in this repository at the experimental tier
([the stability guide](../reference/stability.md)), and its contract terms are unusually precise, because
they are what a reader usually gets wrong:

- **At-least-once effects.** A step that ran may run again after a crash. Every effect a step performs has
  to be safe to repeat, or guarded by something that is.
- **One host, one journal file.** Workers share a journal; there is no multi-host ownership, no
  distributed lock, and no consensus.
- **No exactly-once external effects, and no arbitrary Python checkpointing.** A payload that can be
  journaled is a payload you can describe; a live object graph is not.
- **The experimental boundary is visible in the API.** Entry points emit an `ExperimentalWarning` and the
  package metadata carries the label, so a deployment cannot adopt it by accident.

What it *does* provide is the thing the workflow engine explicitly does not: persisted progress, fenced
single-owner claims, recovery after a crash, cancellation, and inspection of a run that is still going.

## What it is for

An ordinary HTTP handler does not need this. Neither does a request that calls two services. Reach for it
when the work is **multi-step and must survive the process that started it** — an approval that outlives a
deploy, a sequence of external calls that must resume where it stopped, a unit of work somebody will ask
about tomorrow.

| Mode | Guarantee | What it does not promise |
| ---- | --------- | ------------------------ |
| `await direct(...)` | deadline and cancellation for one call | retries, inspection, branching |
| `await workflow.run(...)` | a validated graph, bounded retries, structured events | persistence, recovery |
| `xyberos.durable` | persisted progress, fenced claims, recovery, inspection | exactly-once effects, multi-host ownership |

## What it looks like

`examples/durable_workflow/app.py` is the repository's worked example, exercised by the crash-recovery
suite:

<!-- snippet: examples/durable_workflow/app.py -->

The shape to notice is the **guard**, because it is the honest consequence of at-least-once: a step runs
again after a crash, so the effect it performs is checked against what the journal says already happened.
Recovery is not a retry of the whole run — the executor inspects the journal, decides the next action, and
claims the run with a fence. That is why the recovery decisions have their own tests, including a real
subprocess killed at five different boundaries.

## What to read next

- [Durable execution](../reference/durable.md) — the guide to the store, the worker, and the recovery rules.
- [ADR 0011](../reference/adr/0011-durable-executor-contract.md) — the contract this page summarises.
- [Workflow](../reference/workflow.md) — the engine to use when the work does not need to survive the process.
