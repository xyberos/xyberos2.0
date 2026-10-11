# Durable invoice workflow

Two deterministic demonstrations of progress that outlives the worker running it. Both read their
state from a SQLite journal, not from memory, and neither needs a network or a real clock.

```powershell
cd examples
python -m durable_workflow.app
```

Needs the `durable` extra: `pip install "xyberos[durable]"`.

## What it demonstrates

**Scenario 1 — the worker dies between steps.** Worker A advances one step and is abandoned while
holding nothing (a finished step yields the execution back to the queue). Worker B, which has never
seen the execution, recovers it and finishes the run. Every step ran **exactly once**, because none of
them was ever in doubt.

**Scenario 2 — the worker dies mid-step.** Worker A is killed *after* the `charge` step made its
provider call and *before* its result was persisted. Now nothing can prove whether the charge was
applied:

- worker B cannot take the work at all, because the dead worker's lease is still live;
- when the lease runs out, recovery refuses to guess: the step is recorded `outcome_unknown` and the
  execution is parked in `waiting`;
- the operator supplies a reconciler — the caller's own way of asking the outside world — which
  confirms one charge, and the run finishes with the effect applied **exactly once**.

That second scenario is the whole point of the feature. At-least-once is not a slogan here: it is what
happens when you cannot tell, and the framework's answer is to stop and ask rather than to repeat.

## What to read in the output

- the **step table** shows each step's persisted state and attempt count, which is how you tell a
  reused result from a repeat;
- the **event timeline** is appended, never rewritten, so it is the audit trail for why a run
  resumed, parked, or completed;
- the **effect counts** at the end (`charged`, `receipted`, `notified`) are counted from a file the
  framework does not own, so they are evidence rather than a restatement of the journal;
- the **queue counters** are what an operator watches: `expired_leases` above zero means a worker is
  gone and its work is waiting to be recovered.

## Two things the example is careful about

- **It declares no activity policy for `charge`.** The step takes money, so the safe default applies:
  an interrupted attempt parks the run. Declaring `idempotent=True` would repeat it, which is a
  deliberate choice a caller has to make.
- **The reconciler returns the whole step output**, built by the same function the step uses. A
  reconciler that returns only what it happens to know is accepted by the journal and then fails
  later inside an unrelated step.

## Where to go next

- `docs/durable.md` is the operator guide: the state machine, the recovery table, cancellation,
  backup and retention, incident triage, and the deliberate limits.
- `docs/adr/0011-durable-executor-contract.md` is the frozen contract.
- `tests/crash_recovery/` kills a real subprocess at each documented crash boundary and asserts what
  the journal kept.
