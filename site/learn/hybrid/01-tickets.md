---
title: Tickets as ordinary CRUD
path: hybrid
lesson: 1
tier: built-in
status: verified
verify: output
example: examples/learn_hybrid/hybrid01_ticket_crud.py
---

# Lesson 1 — tickets as ordinary CRUD

## What you will build

The application the rest of this path grows: a support desk where a customer's request is a row, a
state, and a history. Everything in it so far is what the Traditional Apps path already taught —
routes, a service, a database, a page — and that is the point of starting here. **The model arrives
in lesson 4, and nothing before it depends on one.**

The design is fixed before the first line is written, in
[the hybrid design](../../hybrid-design.md): the ticket lifecycle, the permission matrix, the approval
boundary, and the ten lessons with the module each one proves. A decision about who may send an email
is made once, in that page, rather than discovered in lesson seven.

## What you need

The same two extras the traditional path ends with, because this application is built the same way:

=== "PowerShell"

    ```powershell
    python -m pip install "xyberos[http,database]"
    ```

=== "POSIX"

    ```bash
    python -m pip install 'xyberos[http,database]'
    ```

## The project

| File | Owns | Never contains |
| ---- | ---- | -------------- |
| `tables.py` | the columns: tickets, drafts, audit rows, passages, usage rows, the outbox, jobs | SQL, or a rule |
| `security.py` | who is calling, and the roles the matrix names | a ticket |
| `errors.py` | domain refusals, each with its status code | a route |
| `service.py` | the lifecycle, the permission matrix, the audit trail | an HTTP type, or a model call |
| `knowledge.py` | passages, vectors, and the similarity query | a route |
| `mail.py` | the transactional outbox a reply is written to | a decision about sending |
| `triage.py` | the workflow that classifies, grounds, and drafts | authorization |
| `jobs.py` | background triage: the row, the states, and shutdown | a transition |
| `app.py` | providers, routes, and translation | SQL |
| `migrations/` | putting the schema in a database, as a revision | a rule |

`examples/support_desk/tables.py` is the whole schema, and it reads as ordinary application data. The
one thing worth noticing is what the `outbox` table does *not* hold: no draft is ever written to it,
and lesson 7 shows the only code path that writes there at all:

<!-- snippet: examples/support_desk/tables.py -->

The lesson's own module drives the routes and prints what came back:

<!-- snippet: examples/learn_hybrid/hybrid01_ticket_crud.py -->

## How to run it

=== "PowerShell"

    ```powershell
    $env:PYTHONPATH = "src;examples"
    python -m learn_hybrid.hybrid01_ticket_crud
    ```

=== "POSIX"

    ```bash
    PYTHONPATH=src:examples python -m learn_hybrid.hybrid01_ticket_crud
    ```

## What it prints

<!-- output: hybrid01_ticket_crud -->
```text
health: {'status': 'ready', 'model': 'fake-model'}
POST /tickets -> 1 new Where is my refund?
POST /tickets -> 2 new The badge reader is broken
GET /tickets -> 2 of 2
  #1 new  Where is my refund?
  #2 new  The badge reader is broken
PATCH /tickets/1 -> 200 Where is my refund (order 42)?
POST /tickets with no subject -> 422 subject is required
PATCH with an unknown field -> 422 tenant cannot be changed
GET /tickets/1/page -> 200
  the page shows the subject: True
```

Two refusals are in there because they are the ones a first version forgets. `422` for a ticket with
no subject, and `422` for a patch that names a field a client may not change: an unknown field is
refused rather than ignored, which is the difference between a typo that surprises a caller and a typo
that silently does nothing.

The last line is the application's own page — the interface an agent works in, and the reason this
path reuses the traditional one's conventions rather than inventing a second layout.

## Common mistakes

- **Putting a rule in a route.** The route reads the payload and calls the service; the service owns
  what is allowed. A rule in a route is a rule the next route will not have.
- **Letting a client name the tenant.** The tenant comes from the verified principal, never from the
  body. Lesson 2 shows what the other order costs.
- **Returning the row the model changed.** Nothing here returns a row it did not read back, so a
  response cannot describe a write that failed.
- **Forgetting the migration.** The lessons call `migrate(settings)` the way a deploy step does; an
  application that creates its own tables at startup has no deploy step to review.
- **Treating the page as a second API.** The page renders what the service returns. When it needs its
  own query, that is usually a missing service method.

## Next

Lesson 2 adds the assertion that travels with every request: a signature, a tenant, and roles, and the
permission matrix enforced where it cannot be bypassed.
