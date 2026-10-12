---
title: The audit log
path: hybrid
lesson: 3
tier: not-provided
status: verified
verify: output
example: examples/learn_hybrid/hybrid03_audit.py
prerequisites: ["/learn/hybrid/02-principal"]
---

# Lesson 3 — the audit log

## What you will build

The record of who did what. Every transition in `service.py` writes a row **inside its own
transaction**, next to the change it describes, and this lesson reads that trail back. Two properties
are worth the code they cost:

- a trail that can be lost separately from the thing it describes is a trail that will be;
- a trail a model can write is not an audit trail. Nothing in `triage.py` writes an audit row; the
  service does, and the service never calls a model.

This is also the last lesson before the model arrives, so it is the last chance to see the desk as an
ordinary business application: a request comes in, somebody with the right role acts on it, and the
system remembers.

## What you need

Nothing new.

<!-- snippet: examples/support_desk/service.py -->

<!-- snippet: examples/learn_hybrid/hybrid03_audit.py -->

`_record` is called with the caller's `connection` rather than opening its own transaction, which is
what makes the guarantee real: the row and the state change commit together, or neither does. A helper
that opens its own transaction looks identical at the call site and is a different promise.

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid03_audit
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid03_audit
    ```

## What it prints

<!-- output: hybrid03_audit -->
```text
opened     by ada@example.com    Where is my refund?
classified by sam@desk           refund/high
drafted    by sam@desk           fake-model
approved   by sam@desk           A refund takes three business days to appear.
the requester reads the same trail: 4
another requester reads it -> 404 ticket 1 was not found
the audit row keeps the approved body: A refund takes three business days to appear.
```

The `approved` row carries the **body that was approved**, not the fact that something was approved.
That is the row lesson 7's boundary test reads, and it is the reason the trail is worth having: after an
incident, "an agent approved a reply" is not an answer, and "this agent approved this text at this
moment" is.

The requester reads the same four rows for their own ticket, and a different requester in the same
tenant gets a `404`. Reading the trail is reading the ticket, so the visibility rule decides — no
second rule, and no second place to get it wrong.

## Common mistakes

- **A trail written by a fire-and-forget task.** If the row is written after the commit, a crash
  between them leaves a change with no record. Write it in the transaction.
- **Logging instead of recording.** A log line is for an operator and rotates away; an audit row is
  data a reviewer queries, with the columns to answer "who" and "what".
- **Recording that something happened without what it was.** `detail` is the column that makes the
  trail answerable.
- **Letting the trail be edited by the same route that edits the ticket.** Nothing here deletes or
  updates an audit row, and no route offers to.
- **One trail for the wrong tenant.** The tenant is on every row, and the lookup uses it.

## Next

Lesson 4 is where a model enters, and it enters the smallest way possible: one structured call whose
answer the service decides whether to accept.
