---
title: Background processing for slow work
path: hybrid
lesson: 9
tier: built-in
status: verified
verify: output
example: examples/learn_hybrid/hybrid09_background.py
prerequisites: ["/learn/hybrid/08-workflow"]
---

# Lesson 9 — background processing for slow work

## What you will build

The same triage, run behind a job row. The lesson's provider is deliberately slow — four hundred
milliseconds of pretending to think — because that is the whole reason this lesson exists: a model call
can take seconds, and a support desk that holds a connection open for it is a support desk that falls
over when a provider slows down.

The sequence in the transcript is the ask: `202` and a queued job come back **before** the model
answers, the first poll sees `running`, and the job ends as `done` with the ticket at
`awaiting_approval` — with nothing sent, because nothing in this path sends.

The runtime's contribution is `create_task_in_context`: the task carries the caller's context, so the
job's log lines and its correlation id belong to the request that started it. Everything else is
application code, including the part people forget — shutdown waits for work in flight.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/jobs.py -->

<!-- snippet: examples/learn_hybrid/hybrid09_background.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid09_background
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid09_background
    ```

## What it prints

<!-- output: hybrid09_background -->
```text
POST /tickets/1/triage -> 202 {'job': 1, 'state': 'queued', 'ticket': 1}
the job went: queued -> running -> done
it finished as: done with awaiting_approval
the ticket is: awaiting_approval
the draft is waiting for a person: A refund takes three business days to appear.
nothing was sent: 0
```

Three states, and each one earns its place: `queued` is what the request was answered with, `running`
is what a client polls while it waits, and `done` carries the ticket's state as its detail. A job row
that only had "finished" would leave a client unable to tell a slow job from a lost one.

The `detail` on the failed path is the error's **class name**, not its message: the row is server-side
data, and provider messages travel further than people expect.

## Common mistakes

- **Holding the request open.** The cheapest way to keep `p95` honest is to not wait for something
  slow in the request at all.
- **A task with no row.** Work that exists only inside an event loop cannot be polled, retried, or
  reviewed after a restart.
- **Abandoning the work at shutdown.** `aclose` waits. A half-triaged ticket is worse than a slow
  shutdown, and the write is what makes it half.
- **Letting the job's failure become the ticket's failure.** The job records what happened; the ticket
  is untouched until a step succeeds. A failed job leaves a ticket somebody can try again.
- **Polling forever with no terminal states.** Say which states are terminal — here `done` and
  `failed` — and let the client stop.

## Next

Lesson 10 counts what all of this cost, and what the spend bought.
