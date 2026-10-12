---
title: Coordinating the steps with a workflow
path: hybrid
lesson: 8
tier: built-in
status: verified
verify: output
example: examples/learn_hybrid/hybrid08_workflow.py
prerequisites: ["/learn/hybrid/07-approval"]
---

# Lesson 8 — coordinating the steps with a workflow

## What you will build

The three model-facing steps as one graph: classify, ground, then draft — with a branch to `flag` when
the classification is not confident enough to spend a draft on. `xyberos.workflow` is **preview** tier
([stability guide](../../reference/stability.md)), and it is the right tool here for one reason: the
whole sequence has a deadline, and a request that reports "the model was slow" is not a design.

Two properties the transcript makes visible:

- the branch that was not taken is **`skipped`**, not missing, so a run is inspectable;
- a transient provider failure is retried **inside the step that failed**, and the run still finishes —
  the classification count is one more than the number of model-visible steps for that ticket.

The engine's own contract — a validated graph, bounded retries, per-step and whole-run deadlines, and no
loops or parallel steps — is the AI path's [lesson 13](../ai/13-workflows.md). This lesson is that
contract applied to a sequence with a side effect at the end of it.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/triage.py -->

<!-- snippet: examples/learn_hybrid/hybrid08_workflow.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid08_workflow
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid08_workflow
    ```

## What it prints

<!-- output: hybrid08_workflow -->
```text
workflow 'triage' version='1'
steps:   ('classify', 'ground', 'draft', 'flag')
entries: ['classify']
exits:   ['draft', 'flag']
a confident ticket: ticket=awaiting_approval
  {'classify': 'succeeded', 'ground': 'succeeded', 'flag': 'skipped', 'draft': 'succeeded'}
a ticket nobody is sure about: ticket=classified
  {'classify': 'succeeded', 'ground': 'skipped', 'flag': 'succeeded', 'draft': 'skipped'}
after a transient error: ticket=awaiting_approval
  {'classify': 'succeeded', 'ground': 'succeeded', 'flag': 'skipped', 'draft': 'succeeded'}
the flagged ticket says so: flagged - confidence=low: a person classifies this one
model calls so far: 6 (the transient failure was retried)
```

The exits are `draft` and `flag`: the graph ends at a draft, or at a note for a person, and there is no
path in it that sends. A workflow is a place to put side effects, so the shape of it *is* the
authorization story: what is not in the graph cannot happen because of the graph.

The low-confidence ticket's last trail row is `flagged`, written by the branch that decided not to
draft. A trail that records only transitions cannot tell "nothing happened" from "nobody looked", which
is why `record_event` exists.

## Common mistakes

- **A step that does five things.** A step is the unit of retry, timeout, and observation. Five things
  in one step can only be retried as five.
- **Retrying a step with a side effect.** The draft step writes a row; it must stay idempotent or sit
  behind a transition that refuses a second draft once one exists.
- **A whole-run deadline and no per-step timeout.** One slow step is usually the whole story; bound it
  where it happens as well.
- **Expecting parallel steps.** Execution is sequential and conditional by contract. Parallel work
  belongs to the task runtime, not the graph.
- **Confusing the workflow with the policy.** The graph decides the order of *calls*; the service
  decides who may change a ticket. Keep the two apart and the matrix stays readable.

## Next

Lesson 9 runs the same graph in the background, so a slow provider does not hold a request open.
