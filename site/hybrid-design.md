---
title: Hybrid application design
status: verified
---

# The Smart Support Desk: design first

The hybrid path is the last one written and the first one that has to be right, because it consumes
both of the others: the traditional path supplies its CRUD, templates, and verified principal, and the
AI path supplies classification, retrieval, and workflows. This page fixed that design **before** the
path was written, so a decision about who may send an email was made once rather than discovered in
lesson seven. The path is written now — [the ten lessons](learn/hybrid/index.md) are the design,
executed — and this page is what they are checked against: the lifecycle, the matrix, and the boundary
below are the three things `tests/integration/test_hybrid_support_desk.py` asserts.

Nothing here is framework behaviour. Xyberos provides routing, dependency injection, a database
provider, an AI facade, and a workflow engine — the policy below is application code, which is the
point of the exercise.

## Ticket lifecycle

| State | Reached from | Who may cause the transition |
| ----- | ------------ | ---------------------------- |
| `new` | — | any verified principal in the tenant |
| `classified` | `new` | application code, after a call with a response schema returns a category |
| `awaiting_approval` | `classified` | application code, once a draft reply exists |
| `approved` | `awaiting_approval` | `support_agent` or `support_lead` |
| `replied` | `approved` | application code, when it sends the reply |
| `closed` | `replied` | `support_agent`, `support_lead`, or the requester |
| `rejected` | `new`, `classified` | `support_lead` |
| `spam` | `new` | application code, or `support_agent` |

Every transition is a method on the ticket service that takes the principal as a **required
argument**, so forgetting to pass it is a type error rather than a silent authorization bypass — the
shape [ADR 0014](reference/adr/0014-no-identity-or-authorization-model.md) sanctions.

## The permission matrix

| Action | `requester` | `support_agent` | `support_lead` |
| ------ | ----------- | --------------- | -------------- |
| Open a ticket | yes | yes | yes |
| Read tickets in the tenant | own only | all | all |
| Edit a ticket's text | own, while `new` | while `new` | while `new` |
| Run classification | no | yes | yes |
| Read a draft reply | no | yes | yes |
| Approve a reply | no | yes | yes |
| Send a reply | no | via approval only | via approval only |
| Close a ticket | own only | yes | yes |
| Reject or mark spam | no | mark spam only | yes |
| Read the audit log | own ticket | tenant | tenant |

The matrix is enforced in the service layer and asserted by tests. It is not declared to the runtime,
because the runtime has no authorization model to declare it to.

## The approval boundary

**A model never performs an action.** A generated reply is stored as a `SuggestedReply` row attached to
the ticket: it has no send method, and nothing in the application sends it implicitly. Sending requires
an `approve` transition, which records the principal, the timestamp, and the exact body that was
approved, and only then does application code hand the body to the mailer.

This is the rule the whole path exists to teach, so it is tested directly rather than described:

- a suggestion with no approval transition sends nothing;
- an approval by a principal without the role is refused with `403`;
- a request payload that *claims* a different tenant changes nothing;
- the audit log records the decision, the principal, and the body that was approved.

## AI touch points

| Touch point | Label | How it is built |
| ----------- | ----- | --------------- |
| Classification into a category | Built-in | `AIFacade.chat` with a response schema, against the closed JSON Schema subset |
| Reply drafting | Built-in | `AIFacade.chat`, stored as a suggestion and never sent |
| Ticket summarisation | Built-in | `AIFacade.chat` or `structured`, one step in the workflow |
| Knowledge retrieval | You build it | `AIFacade.embed` plus a SQLite table and a similarity query — no index ships |
| Usage, cost, and outcome logging | You build it | ordinary rows written by the workflow's steps |
| Tool use | Not used | The desk calls no tools. The model receives the ticket's text and one retrieved passage, and nothing else: a tool that reads tickets would be a second permission boundary to define, and the path does not need one. The AI path's lesson 11 is where tools belong, and the code for them is the same code with an allowlist in front of it |

Slow model calls run inside the workflow engine with a per-step timeout and a whole-run budget, and the
classification step is the only one that gates a transition — retrieval and drafting are advisory. The
one call that is not inside the graph is the background triage job, which runs the graph itself.

## Lessons, and the example that proves each one

Every lesson is written, and each one is a module the suite runs. The first three are the material the
traditional path also teaches — CRUD, a verified principal, and an audit trail — applied to this
application, which is why the path can spend its model-facing lessons on the boundary rather than on
scaffolding.

| Lesson | Example module | State |
| ------ | -------------- | ----- |
| 1 Tickets as ordinary CRUD | `examples/learn_hybrid/hybrid01_ticket_crud.py` | verified |
| 2 A verified principal, and what it may do | `examples/learn_hybrid/hybrid02_principal.py` | verified |
| 3 The audit log | `examples/learn_hybrid/hybrid03_audit.py` | verified |
| 4 Classification with structured output | `examples/learn_hybrid/hybrid04_classification.py` | verified |
| 5 Knowledge retrieval you build | `examples/learn_hybrid/hybrid05_retrieval.py` | verified |
| 6 Draft replies that are never sent | `examples/learn_hybrid/hybrid06_draft.py` | verified |
| 7 Human approval before sending | `examples/learn_hybrid/hybrid07_approval.py` | verified |
| 8 Coordinating the steps with a workflow | `examples/learn_hybrid/hybrid08_workflow.py` | verified |
| 9 Background processing for slow work | `examples/learn_hybrid/hybrid09_background.py` | verified |
| 10 Logging usage, cost, and outcomes | `examples/learn_hybrid/hybrid10_usage.py` | verified |

## The test that holds it together

The finished application is exercised by `tests/integration/test_hybrid_support_desk.py`, which is
where the phase-5 exit criteria live: the four assertions under [the approval boundary](#the-approval-boundary),
plus one run of the full workflow against `FakeModelProvider` so the suite never needs a model service.

## Shared with the traditional path

The hybrid application uses the same project layout, the same `DatabaseProvider` usage, the same
template approach, and the same `HttpError` shape as the user-management application in the traditional
path, so the two paths teach one set of conventions rather than two.
