---
title: Hybrid application design
status: verified
---

# The Smart Support Desk: design first

The hybrid path is the last one written and the first one that has to be right, because it consumes
both of the others: the traditional path supplies its CRUD, templates, and verified principal, and the
AI path supplies classification, retrieval, tools, and workflows. This page fixes that design before
the path is written, so a decision about who may send an email is made once and not discovered in
lesson seven.

Nothing here is framework behaviour. Xyberos provides routing, dependency injection, a database
provider, an AI facade, and a workflow engine — the policy below is application code, which is the
point of the exercise.

## Ticket lifecycle

| State | Reached from | Who may cause the transition |
| ----- | ------------ | ---------------------------- |
| `new` | — | any verified principal in the tenant |
| `classified` | `new` | application code, after a `structured` call returns a category |
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
| Classification into a category | Built-in | `AIFacade.structured` against the closed JSON Schema subset |
| Reply drafting | Built-in | `AIFacade.chat`, stored as a suggestion and never sent |
| Ticket summarisation | Built-in | `AIFacade.chat` or `structured`, one step in the workflow |
| Knowledge retrieval | You build it | `AIFacade.embed` plus a SQLite table and a similarity query — no index ships |
| Usage, cost, and outcome logging | You build it | ordinary rows written by the workflow's steps |
| Every tool the model may call | Built-in | `ToolSet` with an allowlist: read-only lookups only, and no tool that sends |

Slow model calls run inside the workflow engine with a per-step timeout and a whole-run budget, and the
classification step is the only one that gates a transition — retrieval and drafting are advisory.

## Lessons, and the example that proves each one

Lessons 1–3 are written during the traditional path because they are the same material: CRUD, a
verified principal, and an audit trail.

| Lesson | Example module | Phase |
| ------ | -------------- | ----- |
| 1 Tickets as ordinary CRUD | `examples/learn_hybrid/hybrid01_ticket_crud.py` | 3 |
| 2 A verified principal, and what it may do | `examples/learn_hybrid/hybrid02_principal.py` | 3 |
| 3 The audit log | `examples/learn_hybrid/hybrid03_audit.py` | 3 |
| 4 Classification with structured output | `examples/learn_hybrid/hybrid04_classification.py` | 5 |
| 5 Knowledge retrieval you build | `examples/learn_hybrid/hybrid05_retrieval.py` | 5 |
| 6 Draft replies that are never sent | `examples/learn_hybrid/hybrid06_draft.py` | 5 |
| 7 Human approval before sending | `examples/learn_hybrid/hybrid07_approval.py` | 5 |
| 8 Coordinating the steps with a workflow | `examples/learn_hybrid/hybrid08_workflow.py` | 5 |
| 9 Background processing for slow work | `examples/learn_hybrid/hybrid09_background.py` | 5 |
| 10 Logging usage, cost, and outcomes | `examples/learn_hybrid/hybrid10_usage.py` | 5 |

## The test that holds it together

The finished application is exercised by `tests/integration/test_hybrid_support_desk.py`, which is
where the phase-5 exit criteria live: the four assertions under [the approval boundary](#the-approval-boundary),
plus one run of the full workflow against `FakeModelProvider` so the suite never needs a model service.

## Shared with the traditional path

The hybrid application uses the same project layout, the same `DatabaseProvider` usage, the same
template approach, and the same `HttpError` shape as the user-management application in the traditional
path, so the two paths teach one set of conventions rather than two.
