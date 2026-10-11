# Architecture decision records

Each ADR records a decision that affects public behavior, project structure, or an
implementation boundary. ADRs are immutable after acceptance; superseding decisions add a
new ADR that links to the earlier one.

Status values are **proposed**, **accepted**, **superseded**, and **rejected**.

## Terminology

Documents written before [ADR 0008](0008-workflow-terminology.md) called the in-process execution
unit a *Flow*. It is now a *Workflow*, and the earlier text was updated to the new term; those
decisions are unchanged. `flow` survives in these documents only as ordinary English, as in
"control flow".

## Keeping consequences current

A *decision* is immutable, but a *consequence* is a claim about the future and can go stale.
Consequences may therefore carry a short status note — satisfied in a phase, owned by a named
phase, or deferred to the backlog — without that counting as an amendment. Changing a decision
still requires a new ADR that links back to the original.

Before a phase is declared complete, walk the consequence lists below and confirm each item is
one of: satisfied, owned by a named phase in `implementation.md`, or recorded in its deferred
backlog. Annotate anything newly satisfied, and give an owner to anything that has none.

## Index

| ADR | Decision | Status |
| --- | --- | --- |
| [0001](0001-runtime-boundaries.md) | Keep the runtime small and capability-oriented | accepted |
| [0002](0002-configuration-and-database-stack.md) | TOML configuration and a SQLAlchemy-based SQLite provider | accepted |
| [0003](0003-versions-and-experimental-scope.md) | Begin at 0.0.0 and isolate experimental scope | accepted |
| [0004](0004-initial-ai-provider.md) | Use Ollama as the first AI provider | accepted |
| [0005](0005-phase-1-runtime-contract.md) | Freeze the Phase 1 runtime contract | accepted |
| [0006](0006-http-and-database-adapters.md) | Keep the HTTP and database layers behind adapters | accepted |
| [0007](0007-trusted-plugins.md) | Trusted plugins as an explicit, ordered capability model | accepted |
| [0008](0008-workflow-terminology.md) | Name the in-process execution unit *Workflow* | accepted |
| [0009](0009-workflow-engine-contract.md) | Freeze the workflow engine contract | accepted |
| [0010](0010-ai-facade-contract.md) | Freeze the AI facade contract | accepted |
| [0011](0011-durable-executor-contract.md) | Freeze the durable executor contract | accepted |
| [0012](0012-project-licence.md) | License the project under Apache-2.0 | accepted |
| [0013](0013-stable-surface-and-versioning.md) | Freeze the stable surface and its versioning rules | accepted |
