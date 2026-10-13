---
title: Feature support
status: verified
---

# Feature support

What the framework actually provides, what it defines as an extension point, and what the lesson
teaches you to build. Each lesson on this site carries one of these labels, and
`tests/site/test_lessons.py` checks that a lesson's label agrees with the
[stability guide](reference/stability.md), so this table is enforced rather than aspirational.

| Label | Meaning |
| ----- | ------- |
| **Built-in** | Ships in the framework. An `(extra)` note means an optional install. |
| **Extension point** | The framework ships the contract and a conformance suite; you ship the implementation. |
| **You add it** | A third-party library or server the framework deliberately does not depend on. |
| **You build it** | Nothing ships. The lesson is the implementation. |

## The matrix

| Capability | Import path or tool | Tier | Ships with |
| ---------- | ------------------ | ---- | ---------- |
| Application composition, dependency injection, scopes, lifecycle | `xyberos` | Built-in | core |
| Typed configuration (`Settings`, `xyberos.toml`, `XYBEROS_*`) | `xyberos` | Built-in | core |
| Context and logging helpers, error taxonomy | `xyberos` | Built-in | core |
| Workflow engine: retries, branches, timeouts, cancellation | `xyberos` (`Workflow`, `WorkflowExecutor`, `direct`) | Built-in | core |
| Trusted plugins | `xyberos` (`Plugin`, `PluginRegistry`) | Built-in | core |
| AI facade, contracts, tools, JSON Schema subset, fake provider | `xyberos.ai` | Built-in | core |
| HTTP routing over Starlette | `xyberos.http` | Built-in (extra) | `[http]` |
| SQLite provider and Alembic migrations | `xyberos.database` | Built-in (extra) | `[database]` |
| Ollama adapter | `xyberos.ai.ollama` | Built-in (extra) | `[ollama]` |
| Test doubles: `ManualClock`, `FakeModelProvider`, `temporary_database`, `create_test_client` | the `*.testing` modules | Built-in (extra) | with their extra |
| Command line: `new`, `check`, `run`, `migrate` | the `xyberos` command | Built-in (extra) | per command |
| Database provider contract and conformance suite | `xyberos.database`, `xyberos.database.testing` | Extension point | `[database]` |
| Durable executor | `xyberos.durable` | **Experimental** | `[durable]` |
| HTML templates, static files, CSRF, sessions | Starlette and Jinja2 | You add it | `xyberos-templates` |
| Object storage: filesystem provider and in-memory double | `xyberos.storage` | Built-in | core |
| Storage provider contract and conformance suite | `xyberos.storage`, `xyberos.storage.testing` | Extension point | core |
| MCP tools: consuming a server's tools over streamable HTTP | `xyberos.mcp` | Built-in | core |
| MCP server direction: exposing an application's tools | — | You build it | `xyberos-mcp` |
| Request metrics counters | `xyberos.http` (`RequestMetricsMiddleware`) | Built-in (extra) | `[http]` |
| Logging handler and tracing spans | — | You add it | `xyberos-observability` |
| PostgreSQL, MySQL, MariaDB providers | — | Extension point, nothing shipped | `xyberos-postgres` |
| S3-compatible object storage | — | Extension point, nothing shipped | `xyberos-storage-s3` |
| OpenAI-compatible chat and embedding endpoints | — | You add it | `xyberos-openai-compatible` |
| Redis | — | You add it | — |
| Identity, sessions, roles, tenancy model | — | Not provided, and it will not be | `xyberos-auth` verifies an assertion and stops |
| Vector store, embeddings index, memory, retrieval, intents, agents | — | You build it | — |

## The refusals are features

Three rows above are absences by decision rather than by omission, and each has a recorded reason:

- **No identity or authorization model.** Authorization is a product decision; the framework would get
  it wrong for most users and would own security it cannot verify. The sanctioned shape — verify an
  assertion upstream, pass the principal as an argument, scope queries by it — is in
  [ADR 0014](reference/adr/0014-no-identity-or-authorization-model.md) and is tested in
  [the tenancy example](https://github.com/xyberos/xyberos2.0/tree/master/examples/tenancy).
- **One database provider, and a documented extension point.** SQLite ships; the seam is any async
  SQLAlchemy dialect, and a third-party provider proves itself with `assert_provider_contract`
  ([ADR 0016](reference/adr/0016-database-providers-are-an-extension-point.md)).
- **Durable execution is experimental.** Single host, one journal, at-least-once effects — contract
  terms rather than caveats ([ADR 0011](reference/adr/0011-durable-executor-contract.md)).

## What is never implied

Nothing on this site describes a capability as "supported" unless a test in this repository exercises
it. Where a lesson needs something the framework does not provide, the lesson says so at the top of the
page and shows the code that supplies it.

## Where the labels come from

Every package named in the "Ships with" column above is an entry in
[`packages.toml`](https://github.com/xyberos/xyberos2.0/blob/master/packages.toml) — the manifest of what
lives outside this repository — and `tests/test_packages_manifest.py` checks this matrix against it. That
is what keeps the table a claim about something real: a package that does not exist yet cannot appear here
as shipped, and one that does exist cannot be missing.

Two 1.x names are retired for this line rather than reused. `xyberos-db` points at `xyberos[database]` and
the provider seam, and `xyberos-metrics` points at `xyberos.http.RequestMetricsMiddleware`; both keep their
1.x release and gain a pointer, so nothing moves under a user who pinned them.
