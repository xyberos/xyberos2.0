---
title: Hybrid Apps
status: verified
---

# Build Hybrid Apps

One application that is an ordinary business application *and* uses a model: a support desk where
tickets, permissions, and audit trails are conventional code, and classification, retrieval, and
drafting are AI. The point of the path is the boundary between them.

**AI recommends; application code decides.** A model may classify a ticket, retrieve a passage, or
draft a reply. It never sends one, never changes a permission, and never bypasses a status transition.
That sentence is tested rather than asserted: the boundary has its own integration test in
`tests/integration/test_hybrid_support_desk.py`, and lessons 6 and 7 make it visible in a transcript you
can read.

The design is fixed before the path starts, in [the hybrid design](../../hybrid-design.md): the ticket
lifecycle, the permission matrix, the approval boundary, and the module that proves each lesson. Read it
first if you want to know where this is going; every page below is that design, executed.

## Lessons

| # | Lesson | You will learn | Provided by |
| - | ------ | -------------- | ----------- |
| 1 | [Tickets as ordinary CRUD](01-tickets.md) | The application, its schema, and its routes before any model arrives | Built-in |
| 2 | [A verified principal](02-principal.md) | A signed assertion, the permission matrix, and tenant isolation | You build it |
| 3 | [The audit log](03-audit.md) | Rows written in the same transaction as the change they describe | You build it |
| 4 | [Classification with structured output](04-classification.md) | A model answers, the service decides, and failures stay server-side | Built-in |
| 5 | [Knowledge retrieval you build](05-retrieval.md) | Passages, vectors, and a similarity query — and what it does not prove | You build it (over `embed`) |
| 6 | [Draft replies that are never sent](06-draft.md) | A draft is data: it has no send path, and the outbox stays empty | Built-in |
| 7 | [Human approval before sending](07-approval.md) | Who may approve, what the approval records, and what it unlocks | You build it |
| 8 | [Coordinating the steps with a workflow](08-workflow.md) | Classify, ground, draft, and a branch for the tickets nobody is sure about | Built-in |
| 9 | [Background processing](09-background.md) | A job row, the states a client polls, and shutdown that waits | Built-in |
| 10 | [Usage, cost, and outcomes](10-usage.md) | Tokens, prices, and the column that says what the spend bought | You build it |

**All ten lessons are written.** The [roadmap](../../roadmap.md) is generated from each page's own
status, so it is the authority on what has landed rather than this table.

## What you need

Everything the traditional path ends with, because this application is built the same way:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[http,database]"
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[http,database]'
    ```

## Two things to know before it starts

**One application, not ten.** Every lesson runs against `examples/support_desk/` — the same project, the
same migrations, the same service — and grows it. A page shows the files as the path leaves them, which
is why lesson 1 already contains a table that lesson 10 reads.

**The model is a dependency, not a service.** Lessons hand a provider in when they build the app, so the
suite runs the whole path with no model, no network, and no key: `FakeModelProvider` answers from a
script. Where the answer matters, the page uses a provider that answers exactly what the point needs — a
transient failure, a low confidence, a slow reply.
