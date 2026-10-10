# ADR 0001: Keep the runtime small and capability-oriented

**Status:** accepted

## Context

Xyberos needs lifecycle management, configuration, typed dependency resolution, and a
way to compose optional capabilities without becoming a centralized framework kernel.

## Decision

The core runtime owns only application composition, configuration, provider registration,
dependency validation/resolution, lifecycle, and context/logging hooks. It does not import
HTTP, database, AI, Workflow, or durable-execution implementations.

Capabilities are application-local registrations with explicit contracts, provider scope,
ownership, and cleanup. Dependencies are declared with type annotations and an explicit
marker; parameter names are never used for injection.

> **Later clarification (Phase 5).** "Does not import AI implementations" means the runtime never
> imports `xyberos.ai`, which the import-boundary test asserts. A facade of provider-neutral
> contracts is not an implementation: it pulls in no SDK, and the vendor adapter stays behind an
> extra ([ADR 0010](./0010-ai-facade-contract.md)).

## Consequences

- Each application instance can run independently in the same process.
- Optional packages can be installed and initialized independently of core. *Satisfied in Phase 5:
  the dependency-free facade ships in core while `xyberos.ai.ollama` needs the `ollama` extra, and
  `xyberos.ai` never imports the adapter ([ADR 0010](./0010-ai-facade-contract.md)).*
- New capabilities need a narrow contract and lifecycle ownership before implementation.
