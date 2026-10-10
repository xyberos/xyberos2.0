# Architecture decision records

Each ADR records a decision that affects public behavior, project structure, or an
implementation boundary. ADRs are immutable after acceptance; superseding decisions add a
new ADR that links to the earlier one.

Status values are **proposed**, **accepted**, **superseded**, and **rejected**.

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
