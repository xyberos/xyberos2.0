---
title: Workflows
path: ai
lesson: 13
tier: built-in
status: verified
verify: output
example: examples/learn_ai/ai13_workflows.py
prerequisites: ["/learn/ai/06-errors"]
---

# Lesson 13 — workflows

## What you will build

The sequence, written down: steps that each do one thing, edges that say what may follow, branches that
choose, and deadlines that bound the whole thing. A model call is one step among several, which is what
stops a slow provider from becoming an unbounded request.

`xyberos.workflow` is **preview** tier ([stability guide](../../reference/stability.md)), and its
guarantees are specific: a validated graph, bounded retries, per-step and whole-run deadlines, structured
events, and no orphan tasks. It also promises **no** parallel steps and **no** loops — execution is
sequential and conditional, and cycles are refused at validation.

## What you need

Nothing new.

<!-- snippet: examples/learn_ai/ai13_workflows.py -->

The graph is a value. `build()` returns a `Workflow` that can be rendered, validated, and inspected without
executing anything, which is why the same definition is safe in a log line, a test, and a page like this
one.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_ai.ai13_workflows
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_ai.ai13_workflows
    ```

## What it prints

<!-- output: ai13_workflows -->
```text
workflow 'triage' version='1'
steps: ('classify', 'search', 'answer', 'escalate')
entries: ['classify']
exits:   ['answer', 'escalate']
'how long does a refund take?' -> About your refund: a refund takes three business days
   steps: {'classify': 'succeeded', 'search': 'succeeded', 'escalate': 'skipped', 'answer': 'succeeded'}
'the printer is on fire' -> This needs a person.
   steps: {'classify': 'succeeded', 'search': 'skipped', 'escalate': 'succeeded', 'answer': 'skipped'}
a cycle is refused: workflow 'loop' contains a cycle: a -> b -> a; sequential and conditional execution does not support loops
```

Read the two `steps:` lines: the branch that was not taken is **`skipped`**, not missing. That is what
makes a workflow inspectable — a run records what happened, what was skipped, how many attempts each step
took, and how long it ran, so an incident review does not have to guess.

The last line is validation doing its job: a cycle is refused when the definition is validated, before any
step runs, with the path named (`a -> b -> a`).

## Common mistakes

- **Putting a whole handler in one step.** A step is the unit of retry and observation; a step that does
  five things can only be retried as five.
- **Retrying a step that has side effects.** A step that sends an email and fails after sending will send
  again. Keep the effect in its own step, and make it idempotent or approved (the hybrid path's subject).
- **Expecting parallel execution.** Edge-independent steps still run in declaration order; the engine is
  sequential by contract.
- **Long deadlines "just in case".** A deadline is a promise to the caller; a five-minute budget on a
  request that used to take one second is an outage waiting for a slow provider.
- **Reading state from outside the step.** A step receives its input and returns the next value; a
  workflow that closes over mutable module state cannot be replayed, inspected, or tested.
- **Building the graph inline in a request.** Define it once, validate it at startup, and keep the
  definition next to the code it sequences.

## Next

Lesson 14 composes tools with a workflow: a bounded agent, a budget, and the escalation path when the
answer is not the model's to give.
