# ADR 0001: Keep the runtime small and capability-oriented

**Status:** accepted

## Context

Xyberos needs lifecycle management, configuration, typed dependency resolution, and a
way to compose optional capabilities without becoming a centralized framework kernel.

## Decision

The core runtime owns only application composition, configuration, provider registration,
dependency validation/resolution, lifecycle, and context/logging hooks. It does not import
HTTP, database, AI, Flow, or durable-execution implementations.

Capabilities are application-local registrations with explicit contracts, provider scope,
ownership, and cleanup. Dependencies are declared with type annotations and an explicit
marker; parameter names are never used for injection.

## Consequences

- Each application instance can run independently in the same process.
- Optional packages can be installed and initialized independently of core.
- New capabilities need a narrow contract and lifecycle ownership before implementation.
