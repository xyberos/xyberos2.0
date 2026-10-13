# ADR 0018: The capability-placement rule

**Status:** accepted

## Context

Xyberos 2.0 went to the effort of making its boundary legible ([ADR 0014](0014-no-identity-or-authorization-model.md),
[0015](0015-durability-is-single-host.md), [0016](0016-database-providers-are-an-extension-point.md),
[the positioning page](../positioning.md)), and then faced the question those documents do not answer:
*where does the next capability go?* A framework that answers "somewhere in this repository" grows until
its dependency graph and its promise count are the same as everybody else's; one that answers "somewhere
else" loses the capabilities a small team can legitimately absorb.

The mechanisms were not the problem. 2.0 already ships `register(app)` for providers and routes,
`Plugin` for a distribution the runtime validates and attributes, the provider registry for scopes,
dependencies and test overrides, and extras for an implementation this package ships. Nothing on the
candidate list needed a new mechanism, and a new protocol justified by no candidate is work without a
customer.

What was missing was placement, and placement has four answers rather than two. [ADR 0016](0016-database-providers-are-an-extension-point.md)
had already taken one of them for databases and [ADR 0007](0007-trusted-plugins.md) another for
discovery; this ADR generalizes both.

## Decision

**One rule, four placements, and four constraints that keep the split safe.**

| Placement | Ships as | Applies when |
| --- | --- | --- |
| **Extra, here** | `xyberos[x]`, one working implementation, tested by this repository's suite | it needs a third-party dependency this line accepts (`starlette`, `httpx`, `sqlalchemy`), and it is small enough that this suite can exercise it |
| **Module, here** | a dependency-free module in the package, importable without an extra | it needs nothing from PyPI, so an extra name would gate no import and install no dependency — `xyberos.ai`, `xyberos.storage`, and `xyberos.mcp` all follow this |
| **Package, there** | a distribution in the ecosystem repository | it needs a dependency core will not adopt, it carries policy, or it has its own release cadence |
| **Retire, with a pointer** | the published version stays; a metadata-only patch names the replacement | the capability landed in an extra, so a second distribution would be a second answer to one question |

The four constraints are the part that makes the rule enforceable rather than aspirational:

1. **A package may depend on core; core may never depend on a package or on another package.**
   `python -m pip install xyberos` cannot begin installing things a user did not ask for, which is what
   keeps the dependency audit a page long.
2. **An extra owns paths under `xyberos.*`; a package owns a top-level import root of its own**
   (`xyberos_templates`, `xyberos_auth`, `xyberos_postgres`). Two distributions owning paths under
   `xyberos.*` would make `xyberos/` a namespace package shared across installs, where a partial install
   leaves a half-existing directory, an uninstall leaves stale files, and the import-boundary tests stop
   meaning anything. The corollary is binding in the other direction: **an extra's import path is a
   promise of this package**, so moving `xyberos.storage` into a package later is a breaking change.
   Placement is therefore also an import-path decision, taken before the code rather than with it.
3. **Configuration reaches a package as an explicit argument or through a plugin section.** A capability
   that is not a plugin takes a settings object and exposes a zero-argument async factory — the shape
   `SqliteSettings` plus `sqlite_provider` already ships, and the shape `FilesystemStorageSettings` plus
   `filesystem_storage` copies. A capability that wants a typed section under `[plugins.<name>]` ships a
   `Plugin` whose `config_type` the runtime checks, unknown keys and all. Neither route adds a root key to
   `Settings`, which is what stops "no new mechanism" from quietly becoming one.
4. **One distribution answers one question.** Two names for one capability is one too many, and that
   applies to a revived name as much as to a new one.

**Middleware is not a plugin.** `HttpAdapter(app, middleware=(...))` is the only shape the adapter
offers, so a cross-cutting request concern is a class the application passes. No phase may pretend
otherwise, and no module may install one behind the application's back.

## The candidates, placed

`here` is this repository; `there` is the ecosystem repository, whose name, URL, and owner the
satellite-names decision records (ADR 0022 in the plan's numbering, written when Phase 10 needs it).
`module` and `extra` are both *here* and differ only in whether an extra name is involved.

| Candidate | Placement |
| --- | --- |
| Object storage: the contract, a local-filesystem implementation, a double, and a conformance suite | **module here** (`xyberos.storage`) |
| Request metrics: per-route and per-status counters as a middleware class | **module here**, inside the `http` extra (`xyberos.http.RequestMetricsMiddleware`) |
| MCP tools (consuming a server's tools), streamable HTTP client only | **extra here** (`xyberos[mcp]`) |
| MCP `expose()`, and the stdio transport | **package there** (`xyberos-mcp`) |
| Storage backends with a client library (S3-compatible), PostgreSQL, MySQL | **package there** |
| Templates, static files, forms | **package there** (`xyberos-templates`) |
| A logging preset and tracing | **package there** (`xyberos-observability`) |
| Identity and authentication, verification only | **package there** (`xyberos-auth`) |
| LLM providers other than Ollama | **package there** |
| Multi-tenancy | module or example, either home |
| Parallel fan-out of a workflow step | module here, as an example, and only with the owner's sign-off |
| `xyberos-db`, `xyberos-metrics` | **retire, with a pointer** |
| Introspection output, `check --json`, `--why`, `--schema` | tooling here |
| Sessions, CSRF, an admin UI, OpenAPI, RAG, job queues, rate limiting, feature flags | **refuse** |

## Consequences

- **An extra is a promise the release makes.** It is released with this package, carries its own CI row,
  and must ship one *working* implementation rather than a bare contract. That is why `[http]`,
  `[database]`, `[ollama]`, and `[durable]` each ship a provider, and it is the reason a
  dependency-free capability is placed as a *module* rather than as an empty extra: `pip install
  xyberos[storage]` would install nothing, and an extra that installs nothing is theatre.
- **A capability with no third-party dependency costs nothing to always ship.** `xyberos.ai` established
  it; `xyberos.storage` follows it. The import-boundary tests still hold, because what they forbid is
  core importing another optional *capability*, not core being large.
- **The package repository is where policy and platforms live.** Jinja2, OpenTelemetry, `cryptography`,
  database drivers, and object-store clients each belong to the package that needs them, so this line's
  dependency audit stays a page long and its release cadence stays its own.
- **A conformance suite is the payment for a seam.** Every extension point a package implements ships a
  suite this repository runs against its own implementation first: `assert_provider_contract` for
  databases, `assert_storage_contract` for storage, `assert_model_provider_contract` for AI providers.
  A suite that passes for everything would be worse than none, so each is exercised against deliberately
  broken implementations in this repository's tests.
- **The rule is a decision, not a prohibition.** Reversing a placement takes a new ADR with a reason and
  a cost, which is exactly the bar every refusal in this project already carries.
