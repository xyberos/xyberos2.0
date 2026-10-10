# ADR 0002: TOML configuration and a SQLAlchemy-based SQLite provider

**Status:** accepted

## Decision

Runtime configuration lives in `xyberos.toml`, parsed with `tomllib` on Python 3.11+ and
the `tomli` compatibility dependency on Python 3.10. Explicit application values override
environment variables, which override TOML values, which override safe defaults. Secret
values belong in environment variables or a future secret provider.

The future SQLite provider uses SQLAlchemy 2.x Core with the `aiosqlite` dialect and
Alembic migrations. Xyberos exposes its own provider and transaction boundaries; it does
not require SQLAlchemy ORM models as public framework types.

## Consequences

- `pyproject.toml` remains build metadata rather than deploy-time application settings.
- The database, Ollama, and durable stacks remain optional extras during Phase 0.
- Application and durable journal databases use separate Alembic migration environments.
