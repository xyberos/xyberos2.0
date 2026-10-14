# ADR 0023: A CRUD package beside this line, and the DX work that stays a refusal

**Status:** proposed

## Context

The framework answers "how do I build an internal tool" well and "how do I get a CRUD screen up
quickly" not at all. That second question arrived as a list of four conveniences — ORM integration and
models, form handling with validation and CSRF, resource and route generation, and reusable CRUD
services with filtering, sorting, and pagination — and [ADR 0018](0018-capability-placement-rule.md)
requires each to be placed rather than assumed. Applying its rule to the four, most of them are already
answered:

| Asked for | Where it already is |
| --- | --- |
| Migrations | `xyberos[database]`: `run_migrations` and `apply_migrations` drive Alembic, which [the database guide](../database.md) is explicit about not replacing |
| Form handling | `xyberos-templates`: `read_form` reads urlencoded and multipart bodies |
| Validation | `xyberos.ai.schema`: `validate_payload`, `check_schema`, and `describe_schema` are a JSON Schema subset shipped in core, and [the HTTP guide](../http.md) now shows the four lines that map it to a `422` |
| Resource scaffolding | `xyberos new` scaffolds an application, and the plan puts introspection and its siblings in *tooling here* |

Two more are refused with a recorded reason, and this ADR does not reverse them:

- **An ORM, models, and repository base classes.** [The positioning page](../positioning.md) lists "a
  batteries-included application" as a poor fit *because* there is no ORM, names Django and FastAPI plus
  SQLAlchemy as the alternative for a team that wants one, and [the database guide](../database.md) states
  that ORM sessions are not a framework abstraction. Reversing that is a decision about what this project
  is, not a package.
- **CSRF and server-side sessions.** Refused by [ADR 0018](0018-capability-placement-rule.md) with an admin
  UI, OpenAPI, RAG, job queues, rate limiting, and feature flags. Starlette ships the middleware, so the gap
  costs a reader an install rather than a capability.

What remains is the fourth item, and it is the only one that is neither shipped nor refused.

## Decision

**Propose one package: `xyberos-crud`, carrying query construction over `DatabaseProvider` and nothing
else.** It is placed as a *package there* by [ADR 0018](0018-capability-placement-rule.md)'s rule, because it
carries policy — which filter operators exist, and whether pagination is offset-based or keyset — and that is
the stated criterion for the placement.

- **It exposes values, not entities.** A filter set, a sort list, and a page request, applied to a SQLAlchemy
  Core `select()`. It does not map rows to objects, does not own identity, and does not wrap
  `DatabaseProvider`: a service still opens its own transaction, which is the boundary
  [ADR 0016](0016-database-providers-are-an-extension-point.md) draws.
- **It builds on the contract, so it works with every provider.** `DatabaseProvider` is three members over an
  `AsyncConnection`, so the package works against the shipped SQLite provider and against
  `xyberos-postgres` with no core change.
- **Its settings arrive as an explicit argument**, never as a new root key in `Settings`
  ([ADR 0018](0018-capability-placement-rule.md), constraint 3). Limits that a deployment must set — a maximum
  page size, which operators are allowed to reach the database — are fields on that object.
- **Its conformance target is the self-check shape**, because core ships no suite for this seam. The job
  installs the published core and the package and asserts the package's public names import against it.
- **One name answers one question.** Filtering, sorting, and pagination are one question — "how is a
  collection query described" — so they are one distribution rather than three.

**The line it may not cross.** A filter builder is one refactor away from an ORM, and an ORM is the refusal
above. The test is whether the package can answer a query without knowing what a row *means*: it takes a
table and returns a statement, so it can. A future ADR that gave it entity mapping, identity, or a session
would be reversing the positioning decision, and would need to say so.

## Consequences

- **The backlog's CRUD gap becomes a placement.** The four conveniences are now: three shipped, two refused,
  one proposed. Nothing in this document ships, and no manifest row exists until the owner accepts it and the
  distribution is written.
- **The package cannot be published until it has a check, which the self-check shape supplies.** That is the
  same gate every other package beside this line passes; it is not a weaker promise, it is the honest one.
- **It must declare a floor that carries what it imports.** The last core release proved the range is not
  enough on its own: `xyberos-storage-s3` declares `xyberos>=2,<3`, an environment already on `2.0.0` satisfies
  it, and the install produces an `ImportError` because `xyberos.storage` arrived in `2.1.0`. A package that
  imports a name added after `2.0.0` states the release that added it.
- **No core change is needed, which is the point.** The seam that makes this possible —
  `DatabaseProvider` — was declared in [ADR 0016](0016-database-providers-are-an-extension-point.md) for a
  different reason, and this is the first capability to arrive through it that is not a database backend.
- **An admin UI stays refused.** Filtering and pagination are what an admin UI is built *from*; generating the
  screens remains the application's work, and a package that did it would be the batteries-included framework
  [the positioning page](../positioning.md) declines to be.
