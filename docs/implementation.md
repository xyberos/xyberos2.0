# Xyberos implementation plan

> Implementation status: Phases 0–8 are complete. The repository is at `2.0.0`, the first release of
> this line ([ADR 0017](adr/0017-release-identity-and-lineage.md)): the app
> runtime, the Starlette HTTP adapter with the SQLite provider, the trusted plugin/capability model,
> the Workflow engine, the optional AI facade, the experimental durable executor, the frozen public
> surface, and the release engineering. The phase table under "Phase status" is the at-a-glance state,
> and nothing is released until the project owner signs the release gate.

## Purpose and release boundary

Ship a small, well-tested Python application framework whose stable surface is:

- application composition, lifecycle, configuration, and typed dependencies;
- Starlette-backed HTTP applications;
- SQLite-backed application data through a replaceable provider;
- in-process, explicit `Workflow` execution; and
- in-process, trusted plugins.

The SQLite durable executor is an opt-in **experimental** package. It must not be imported, configured, or migrated by a normal application. It is single-host only, and must never be described as exactly-once execution.

## Review of `PLAN.md`

> Status: recommendations 1–8 below are all accepted. Items 1, 2, 3, and 5 are implemented by
> Phases 0–1; items 4 and 8 are scheduled in the phases that own them; items 6 and 7 belong to
> Phase 4. The external review of this baseline is dispositioned in `PLAN.md` Appendix A.

### What is already strong

The architectural boundary between capability registration (what services exist) and execution (how work runs) is the right foundation. The plan also makes three important scope decisions: direct calls remain the default, Workflow is explicit, and durability cannot block the stable release. The acceptance criteria and test categories are good starting quality gates.

### Recommendations to adopt before implementation

1. **Write API contracts before modules.** Phase 0 needs versioned, executable API examples and decision records for `App`, `Inject`, provider scope, plugin lifecycle, `Workflow`, and error types. This prevents the proposed directory layout from becoming the de-facto design.
2. **Make lifecycle and DI graph validation precise.** Validate the provider graph at startup, including missing providers, cycles, scope violations, and incompatible types. Construct lazy app-scoped services on first use unless they opt into eager startup; validation must still happen before traffic. This avoids expensive or side-effectful construction merely to validate an app.
3. **Define the scope model explicitly.** Use only `app`, `request`, and `transient` initially. A request-scoped dependency may depend on app-scoped services but not the reverse. Workflow execution context is not a DI scope; Workflow input/state must be passed explicitly.
4. **Separate SQLite files, not just tables.** Use one application database and a separate executor-journal database. Enable WAL mode at database creation, set a bounded `busy_timeout`, keep write transactions short, and document that SQLite still permits one writer at a time. `synchronous=NORMAL` is a performance/durability trade-off and should be an explicit configurable default, not an unconditional guarantee.
5. **Treat context propagation as observability, not authorization.** Store trace/correlation IDs in `contextvars` and copy context when crossing into threads or custom background workers. `asyncio.create_task` already copies the current context at task creation on supported Python versions. Do not rely on ambient context for identity, tenancy, permissions, or transaction handles; pass those explicitly and re-authorize background work.
6. **Keep Workflow definitions declarative first.** A builder API produces an inspectable graph and is compatible with retries, tracing, and future durability. A decorator/imperative API can be evaluated later, but arbitrary Python control flow cannot reliably be inspected or recovered. Do not make it part of the first stable Workflow contract.
7. **Use AI adapters as Workflow test fixtures, not a reason to reorder core work.** Define the provider protocol and a deterministic fake during Workflow development. Deliver the public AI facade after Workflow semantics stabilize, while using simulated slow/failing calls to test retries, deadlines, cancellation, and usage reporting.
8. **Add compatibility and security boundaries.** Publish supported Python and Starlette version ranges, plugin API versioning, configuration precedence, secret redaction, and a public-versus-internal import policy before accepting third-party plugins.

### Corrections and clarifications

- A persisted activity result does not prove an external side effect occurred once. Durable activities require an idempotency key, an idempotent operation, or a documented reconciliation policy.
- Lease ownership needs a monotonically increasing fencing token. Every state-changing commit must condition on the current owner and token, so a stale worker cannot commit after a lease is reclaimed.
- Timeout terminology needs two levels: a cooperative step deadline and a whole-workflow deadline. Python cannot safely kill arbitrary in-process code; cancellation is cooperative and blocking/CPU-bound work needs a documented executor policy.
- The current `PLAN.md` contains mojibake (for example, `â€”` in headings and tree characters). Re-save it as UTF-8 before publishing it as project documentation.

## Technical decisions to lock in Phase 0

| Area | Decision |
| --- | --- |
| Python baseline | Python 3.10+; CI tests every supported minor version. Use `typing.Annotated` and `contextvars`; provide a small `TaskGroup` compatibility layer because `asyncio.TaskGroup` starts in Python 3.11. |
| Public package | `xyberos` is the sole stable import root; modules not re-exported from it are internal until documented otherwise. |
| Configuration | `xyberos.toml`, parsed with stdlib `tomllib` on Python 3.11+ and `tomli` on 3.10. Precedence is explicit arguments, environment, file, then defaults. Keep secrets in environment variables and redact them in errors/diagnostics. |
| Providers | Providers declare key/type, factory or instance, scope, dependencies, and optional close hook. Duplicate keys fail unless an explicit replacement/override is active. |
| Lifecycle | `register -> validate -> start -> ready -> stop`; startup follows dependency order and shutdown reverses successfully started resources. Collect shutdown failures without skipping later cleanup. |
| Plugins | Trusted, in-process Python code with a name, API version, declared dependencies, `register`, optional async `start`, and optional async `stop`. No entry-point auto-discovery in the first cut unless explicitly configured. |
| HTTP | Thin Starlette adapter. Runtime readiness completes inside ASGI lifespan before routes accept requests. |
| Database | SQLAlchemy 2.x Core with the `aiosqlite` async dialect, plus Alembic migrations. Xyberos owns configuration and transaction ownership; it does not require applications to adopt SQLAlchemy ORM. |
| Workflow | Declarative named graph; unique immutable step IDs; serializable metadata; explicit retry, timeout, and error policy. |
| AI | Ollama is the first provider, implemented as an optional `xyberos[ollama]` adapter over its HTTP API. It must not be imported or contacted by core. |
| Versioning | Development begins at `0.0.0`, a working placeholder; this line releases as `2.0.0`, where the leading digit records lineage rather than maturity ([ADR 0017](adr/0017-release-identity-and-lineage.md)). The project follows SemVer/PEP 440, and the stable, preview, and experimental tiers are declared in [stability.md](stability.md); plugin, configuration, Workflow-definition, and journal-schema compatibility are versioned independently. |
| Optionality | Ollama and durable dependencies are extras, e.g. `xyberos[ollama]` and `xyberos[durable]`; importing core must not load either. |

## Adopted implementation decisions

### Python support policy

Xyberos supports CPython **3.10 and newer**. CI must test 3.10, the current supported Python minors, and the newest stable CPython release. Type hints use `from __future__ import annotations` where needed to keep 3.10 support clean.

`asyncio.TaskGroup` is not available in Python 3.10. The runtime must expose its own small structured-concurrency abstraction with identical documented cleanup semantics, implemented using `TaskGroup` on 3.11+ and a tested compatibility implementation on 3.10. No public API may require a caller to depend directly on `TaskGroup`.

When a Python minor reaches end of life, removal is announced in a minor release and takes effect only in the next Xyberos major release, except where an urgent security/runtime incompatibility requires a documented exception.

### SQLite access and migration stack

Adopt the following implementation stack:

| Concern | Selection | Rationale |
| --- | --- | --- |
| Database toolkit | SQLAlchemy 2.x Core | Mature SQL construction, connection/transaction management, async support, and a credible path to future providers without imposing ORM entities on users. |
| SQLite async driver | `aiosqlite` | Integrates with SQLAlchemy's async SQLite dialect and keeps database calls off the ASGI event-loop thread. It still serializes work per SQLite connection and does not remove SQLite's single-writer constraint. |
| Migrations | Alembic | The established SQLAlchemy migration tool; it supports async integration and SQLite batch/table-rebuild migrations. |
| Mapping style | SQLAlchemy Core first | The framework exposes provider/transaction boundaries and does not make SQLAlchemy ORM models part of the Xyberos public API. Applications may use the ORM privately. |

Place these in a `database` optional dependency group rather than core, for example `sqlalchemy>=2.0,<2.1`, `aiosqlite>=0.20,<1`, and `alembic>=1.13,<2`; resolve and lock exact tested versions in the project lock/constraints file. Exact lower bounds must be verified against the selected Python support matrix before release.

Use `create_async_engine` with the `sqlite+aiosqlite` dialect. The provider owns engine lifetime and supplies an explicit async transaction context; an `AsyncSession` must never be shared across concurrent tasks. Configure each newly opened SQLite connection with foreign keys enabled, WAL where supported, a bounded busy timeout, and the selected synchronous policy. The database provider documentation must state that `aiosqlite` uses a worker thread per connection rather than true non-blocking SQLite I/O, so it improves event-loop behavior but not write parallelism. [SQLAlchemy SQLite documentation](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html) describes the dialect and its pooling behavior; [Alembic's SQLite batch guidance](https://alembic.sqlalchemy.org/en/latest/batch.html) explains why some SQLite schema changes require a table-rebuild migration.

Use one Alembic migration environment for application data and a separate, durable-extra migration environment for the journal database. Never auto-run migrations at normal production application startup; make migration execution an explicit CLI/deployment action. Automatic migration is acceptable only for an isolated local-development template with a clearly marked option.

### Configuration format and precedence

Adopt **TOML** in a dedicated `xyberos.toml` file. TOML fits Python packaging conventions, is readable for nested typed configuration, has a standard-library parser from Python 3.11 onward, and needs only the small, well-established `tomli` fallback on 3.10. Do not use `pyproject.toml` for runtime application settings: package-build metadata and deploy-time configuration have different owners and lifecycles. PEP 680 documents the standard-library `tomllib` addition and its `tomli` basis. [PEP 680](https://peps.python.org/pep-0680/)

The loader checks an explicit config path first; otherwise it checks `XYBEROS_CONFIG`, then `./xyberos.toml`. It fails with a clear error if an explicitly requested file is missing or malformed. There is no upward directory search, which avoids accidentally loading a parent project's settings.

Settings use this precedence, highest to lowest:

1. explicit `App(settings=...)` values supplied by the embedding application;
2. environment variables prefixed `XYBEROS_`;
3. values in `xyberos.toml`;
4. documented safe defaults.

Map nested environment settings with double underscores, for example `XYBEROS_DATABASE__URL` maps to `[database] url`. Parse environment values through the same typed schema as TOML values; reject unknown keys by default, except for an explicit `extra = "allow"` extension namespace if the plugin contract later requires it.

```toml
schema_version = 1

[app]
name = "support-service"
environment = "development"

[database]
url = "sqlite+aiosqlite:///./var/app.db"
busy_timeout_ms = 5_000
journal_mode = "WAL"
synchronous = "NORMAL"

[ai.ollama]
base_url = "http://127.0.0.1:11434"
model = "llama3.2"
request_timeout_s = 60
```

TOML is for non-secret settings. Secrets such as provider credentials belong in environment variables or an application-supplied secret provider, never committed configuration. The loader must redact values for fields classified as secrets in logs, validation errors, and diagnostics. `schema_version` is mandatory from the first public config format and is migrated/validated before other settings are consumed.

### First AI provider: Ollama

Ollama is the first provider because it offers a local HTTP API and supports the required initial facade capabilities: chat, streaming, embeddings, JSON-schema structured outputs, and tool-call payloads. The adapter uses the documented HTTP API directly through an internal async HTTP client, rather than making an Ollama Python SDK part of the framework contract. This keeps provider-specific types isolated and makes requests straightforward to mock. Ollama documents tool calls and JSON-schema `format` structured outputs in its [API documentation](https://docs.ollama.com/api).

The `xyberos[ollama]` extra contains the adapter and its HTTP-client dependency. Core import, application startup, and tests must not require the Ollama service, a downloaded model, or an accelerator. The adapter's default base URL is `http://127.0.0.1:11434`, but the model is **required configuration** in production; `llama3.2` may appear only in examples. Xyberos never pulls, starts, stops, or upgrades an Ollama model automatically.

The first adapter release includes:

- non-streaming and streaming chat completion;
- embeddings through the current Ollama embedding endpoint;
- structured output by sending a JSON schema and then independently validating the returned payload;
- tool-call parsing and Xyberos-side validation/authorization before any tool is executed;
- configurable connect/read/overall timeouts, cancellation propagation, request IDs, model metadata, and normalized errors; and
- a health/readiness check that distinguishes an unreachable service, unavailable model, and model response failure.

Model capabilities vary. The adapter must not infer that a model supports tools or structured output merely because the Ollama API accepts those fields. It validates configured capability claims at initialization where possible, retains response validation at runtime, and reports an actionable unsupported-capability error. Prompt and response content remain excluded from logs by default.

### Recommended versioning and compatibility policy

The distributable package begins at **`0.0.0`** as a working placeholder and releases as **`2.0.0`**, following [Semantic Versioning 2.0.0](https://semver.org/) together with PEP 440 spelling for Python packaging. The leading digit records **lineage**, not maturity: the `xyberos` name is held on the package index by the already-published 1.x line, which installs the same import root, so this line cannot be `0.x` or `1.0.0` ([ADR 0017](adr/0017-release-identity-and-lineage.md)). Maturity is declared by the classifier and by the tiers in [stability.md](stability.md). Development releases use forms such as `2.0.0.dev1`, `2.0.0a1`, `2.0.0b1`, and `2.0.0rc1`; pre-releases are opt-in and never selected by a normal compatible-version constraint.

| Version change | Permitted changes | Compatibility obligation |
| --- | --- | --- |
| Patch `2.x.y` | Bug fixes, documentation, and internal changes. | No break to a documented name in any tier; document every user-visible change. |
| Minor `2.x.0` | Backward-compatible features, new optional capabilities, deprecations, and breaking changes to a **preview** name. | Stable names keep working. A preview break needs an "Upgrade notes" entry and migration assistance where practical. Do not silently reuse configuration or persisted-data meanings. |
| `2.0.0` | First release of this line: the stable runtime and Workflow surfaces defined in this plan. | Freeze the documented public contract and start the stable-major policy below. It breaks compatibility with the published 1.x line, which is a different codebase. |
| Major `3.0.0` and later | Removal of deprecated API, changed stable semantics, supported-Python removal, or incompatible config/plugin/protocol change. | Migration guide, automated migration where feasible, and an overlap/deprecation period in the preceding stable major/minor line. |

Before the first release of this line, every documented surface is preview unless explicitly marked stable for a limited contract. From `2.0.0`, stable public API comprises documented imports under `xyberos`, documented CLI commands, `xyberos.toml` schema, provider/plugin protocols, documented Workflow definition format, and documented error fields. Internal module paths and underscored APIs have no compatibility promise. Experimental APIs live under `xyberos.experimental` or an explicitly marked optional package and may change in a **minor** release; every such change is listed prominently in release notes and emits `ExperimentalWarning` where practical.

Compatibility is independently versioned where persisted or third-party contracts demand it:

| Contract | Policy |
| --- | --- |
| Plugin API | `PLUGIN_API_VERSION = 0` while the plugin protocol is preview. Plugins declare a package range such as `>=2,<3`; a different plugin API major is rejected before startup. It becomes `PLUGIN_API_VERSION = 1` when that protocol is promoted to the stable tier, which is a deliberate decision rather than a release step ([ADR 0013](adr/0013-stable-surface-and-versioning.md)). |
| Configuration schema | `schema_version = 1`. A minor release may add keys or make a documented breaking correction with upgrade notes; silently changing a key's meaning is forbidden. Breaking removal or reinterpretation requires a new schema version plus migration guidance and support for the prior schema for at least two minor releases whenever feasible. |
| Workflow definition format | Explicit `definition_version`. An incompatible meaning requires a new version and release note while the format is preview. Once a format version is stable, it is readable for the complete major release; an incompatible meaning requires a new version and converter or rejection before execution. |
| Durable journal schema | Alembic revision plus journal `schema_version`. Upgrade is forward-only in normal operation, tested from every supported prior journal revision, and never automatic at production app startup. |
| Serialized events/errors | Additive fields only within a major release. Consumers must ignore unknown fields. |

Deprecation policy: mark a stable API deprecated in documentation and runtime warnings in one minor release, retain it for at least two subsequent minor releases or six months (whichever is longer), and remove it only in the next major release. Security or data-corruption fixes may bypass this period, with a release-note explanation. The changelog must include an "Upgrade notes" section for every minor and major release.

## Phase status

The detailed work packages live in the phase-by-phase plan below; this table is the at-a-glance
state. Phases 0–8 are complete. Nothing is released: the release decision itself is the project
owner's and no artefact is published before it.

| Phase | Scope | Status | Exit-gate evidence |
| --- | --- | --- | --- |
| 0 | Architecture, repository, and API contracts | complete | installable core package, ADR set, CI quality gates, contract examples |
| 1 | Application runtime, registry, lifecycle, and dependency injection | complete | `tests/runtime/`, `tests/test_public_api.py`, `tests/contracts/test_contract_examples.py`, `docs/runtime.md`, [ADR 0005](adr/0005-phase-1-runtime-contract.md) |
| 2 | Starlette adapter and SQLite CRUD slice | complete | `tests/http/`, `tests/database/`, `tests/integration/`, `tests/test_import_boundary.py`, `examples/sqlite_crud/`, [ADR 0006](adr/0006-http-and-database-adapters.md) |
| 3 | Trusted plugin and capability model | complete | `src/xyberos/plugins/`, `src/xyberos/diagnostics.py`, `tests/plugins/`, `tests/integration/test_plugin_packages.py`, `tests/fixtures/metrics_plugin/`, `examples/custom_plugin/`, [ADR 0007](adr/0007-trusted-plugins.md) |
| 4 | Stable, in-process Workflow engine | complete | `src/xyberos/execution/`, `tests/workflow/` (107 tests), `tests/integration/test_workflow_example.py`, `tests/contracts/examples/phase4_workflow.py`, `examples/workflow/`, `docs/workflow.md`, [ADR 0009](adr/0009-workflow-engine-contract.md) |
| 5 | Optional AI facade | complete | `src/xyberos/ai/`, `tests/ai/` (125 tests), `tests/integration/test_ai_assistant.py` (11 tests), `examples/ai_assistant/`, `docs/ai.md`, [ADR 0010](adr/0010-ai-facade-contract.md) |
| 6 | Experimental single-host durable executor | complete | `src/xyberos/durable/` (10 modules), `tests/durable/` (100 tests), `tests/crash_recovery/` (17 process-kill tests), `tests/integration/test_durable_example.py`, `examples/durable_workflow/`, `docs/durable.md`, [ADR 0011](adr/0011-durable-executor-contract.md) |
| 7 | Developer experience, hardening, and release | complete (release decision pending owner sign-off) | all seven work packages: `docs/stability.md` + [ADR 0013](adr/0013-stable-surface-and-versioning.md) + `tests/test_public_surface.py` + `tests/test_compatibility.py` + `tests/test_deprecation.py` + `src/xyberos/deprecation.py`; `docs/getting-started.md`, `docs/testing.md`, `docs/troubleshooting.md`, `docs/security.md`, `examples/hello_app/`; `src/xyberos/cli/` + `docs/cli.md` + `tests/cli/`; `CHANGELOG.md`, `SECURITY.md`, `docs/release.md`, `tests/test_release_artefacts.py`; `tests/perf/` + `docs/performance.md`; the threat review with two credential-echo defects fixed |
| 8 | Boundary legibility and extension points | complete | [ADR 0014](adr/0014-no-identity-or-authorization-model.md), [0015](adr/0015-durability-is-single-host.md), [0016](adr/0016-database-providers-are-an-extension-point.md); `docs/positioning.md`, `docs/database-providers.md`; `assert_provider_contract` in `xyberos.database.testing` + `tests/database/test_provider_contract.py`; `examples/tenancy/`, `examples/broker_worker/` and their integration tests; the write-throughput baseline |

### Phase 7 entry checklist

Confirmed when Phase 7 opened; the rows below record how, and the release decision gate in the Phase 7
work package section is now the live gate.

1. Phases 0–6 are complete and every public contract is frozen in an ADR: runtime
   ([0005](adr/0005-phase-1-runtime-contract.md)), HTTP/database
   ([0006](adr/0006-http-and-database-adapters.md)), plugins
   ([0007](adr/0007-trusted-plugins.md)), Workflow
   ([0009](adr/0009-workflow-engine-contract.md)), AI
   ([0010](adr/0010-ai-facade-contract.md)), durability
   ([0011](adr/0011-durable-executor-contract.md)), and now the surface itself
   ([0013](adr/0013-stable-surface-and-versioning.md)).
2. Durable execution is explicitly experimental *and* its exit gate is met, so Phase 7 has to choose
   between promoting it and omitting it from the release; either way it must not block the stable
   runtime. Its promotion criteria are `PLAN.md` section 5.4. **Not promoted by this phase's default:
   the release decision gate carries "durable (experimental)" as a row, so the release can ship with
   durability present and labelled, or omitted.**
3. Both optional surfaces are complete enough to document as preview: the AI facade ships in core
   with only adapters behind extras, and the durable package is behind the `durable` extra with a
   separate journal.
4. Known backlog items are dispositioned rather than quietly carried: the decorator Workflow API,
   parallel steps, the step-executor boundary, richer schema keywords, streaming tool calls, and the
   AI/RAG subsystem are all recorded as deferred, and the ones needing a new ADR say so.
5. The owner decisions in "Remaining owner decisions" are settled — the license and the AI
   release/model/retention policies are decided; only the contributor terms (DCO versus CLA) and any
   promotion of durable execution remain open, and both have a decision point rather than a
   dependency.


## Detailed phase-by-phase execution plan

The phases are intentionally sequential at their public-contract boundaries. Work inside a phase can proceed in parallel only after its API contract is accepted. Do not begin a dependent phase by importing unfinished internal modules; use a fake contract implementation instead.

### Phase 0 - architecture, repository, and API contracts

**Objective:** make the first implementation decisions reviewable and make every later phase start from a reproducible development environment.

**Prerequisites:** the adopted Python, configuration, database, Ollama, and versioning decisions above are recorded as accepted ADRs. The project owner selects the license before distribution; it does not block local architecture work. **Resolved:** the license is Apache-2.0, declared in metadata from Phase 0's `pyproject.toml` ([ADR 0012](adr/0012-project-licence.md)).

**Work packages**

1. Create the `src/` package layout, `pyproject.toml`, lock/constraints policy, editable-install workflow, README, contribution guide, and test layout. Set `requires-python = ">=3.10"`; core, database, Ollama, and durable dependencies must be separate extras from day one.
2. Configure a formatter, linter, type checker, test runner, coverage threshold, dependency audit, and build verification. Add CI jobs for each supported Python version and for core-only, AI-extra, and durable-extra installation.
3. Write ADRs for the adopted database stack, TOML loader, Ollama adapter, and versioning policy, plus runtime ownership, DI scopes, lifecycle ordering, HTTP adaptation, Workflow semantics, durable-execution limits, plugin trust, logging/redaction, and public-import policy.
4. Add executable API examples for a minimal app, an injected service, a SQLite transaction, a plugin, and a simple Workflow. These are contract tests, not merely documentation snippets.
5. Establish the error taxonomy. Errors must include safe, actionable context and preserve root exceptions. The taxonomy is introduced incrementally by the phase that owns each family: Phases 0–1 define configuration, registration, dependency-resolution, and lifecycle errors; Phase 2 adds HTTP-adaptation and database errors; Phase 3 adds plugin and provider errors; Phase 4 adds Workflow-validation and Workflow-execution errors; Phase 6 adds durable-state errors and defines `ExperimentalWarning`, the warning category every experimental API emits (ADR 0003).
6. Define documentation conventions: stable versus experimental labels, version support policy, deprecation policy, and the rule that all public examples are tested in CI.

**Implementation detail:** keep the initial root module deliberately small. Public re-exports should be explicit, and every other module is internal unless the docs say otherwise. This creates freedom to reorganize implementation files without an accidental compatibility commitment.

**Verification and exit criteria**

- A fresh virtual environment can install the wheel and run the minimal example without optional extras.
- Format, lint, type checking, tests, package build, and documentation-example tests run in one documented command.
- Contract tests compile and execute the intended public APIs, using temporary fakes where a subsystem is not yet implemented.
- CI tests both source and built-wheel installation, so missing package data and accidental imports are found early.

**Deliverables:** repository baseline, CI workflow, ADR set, contribution guide, public API contract tests, and a minimal runnable app example.

### Phase 1 - application runtime, registry, lifecycle, and dependency injection

**Status:** complete. [`src/xyberos/app.py`](../src/xyberos/app.py),
[`src/xyberos/config.py`](../src/xyberos/config.py),
[`src/xyberos/errors.py`](../src/xyberos/errors.py), and
[`src/xyberos/runtime/`](../src/xyberos/runtime/) implement the public runtime; the
exit-criteria tests live in [`tests/runtime/`](../tests/runtime/) and
[`tests/test_public_api.py`](../tests/test_public_api.py); the executable example and the
[runtime guide](runtime.md) are in place.

**Objective:** implement application composition without HTTP, database, AI, or Workflow dependencies.

**Prerequisites:** Phase 0 contracts for `App`, provider records, scopes, lifecycle, configuration, and errors are accepted.

**Work packages**

1. Implement typed configuration loading and validation. Inputs are explicit constructor arguments, then environment variables, then selected config file/default values. Return field-level validation errors without echoing secret values.
2. Implement an application-local registry. A provider record includes its contract key/type, factory or supplied instance, declared dependencies, scope, ownership/close hook, source plugin, and eager/lazy flag.
3. Build a dependency graph from registration metadata and annotations. On validation, reject missing providers, ambiguous providers, cycles, unsupported annotations, and illegal scope edges. Error output must show the resolution path and registration source.
4. Implement `app`, `request`, and `transient` resolution. Cache app-scoped instances on the app and request-scoped instances on the request context; construct transient instances each time. A longer-lived service may not capture a shorter-lived service.
5. Implement `register -> validate -> start -> ready -> stop`. Start dependencies first. On a partial startup failure, stop only successfully started resources in reverse order. On shutdown, attempt all cleanup and raise/record an aggregated cleanup failure only after cleanup completes.
6. Provide context helpers for correlation IDs, logger bindings, cancellation/deadline metadata, and safe background-task creation. Context variables are copied deliberately across custom worker/thread boundaries.
7. Implement test-only overrides as a bounded context manager or app clone. Overrides must never mutate global state or bleed to parallel tests.

**Non-goals:** parameter-name DI, a global service locator, auto-wiring arbitrary classes, nested custom scopes, and automatic thread/process execution.

**Verification and exit criteria**

- Two applications with different config and overrides run concurrently in one interpreter without cross-talk.
- Unit tests prove graph ordering, cycle reports, app/request/transient cache behavior, illegal-scope rejection, lazy construction, eager-start behavior, and reverse cleanup after each failure point.
- Test cases prove that a failure before readiness prevents work from being accepted and that all shutdown hooks receive a chance to run.
- Public type checking accepts `Annotated[T, Inject()]` and rejects injection without an explicit marker where the API requires one.

**Deliverables:** `App`, registry and DI APIs, lifecycle engine, configuration module, context/logging primitives, runtime documentation, and isolated-app tests.

### Phase 2 - Starlette adapter and SQLite CRUD vertical slice

**Status:** complete. `src/xyberos/http/` and `src/xyberos/database/` implement the adapter and
provider; tests live in `tests/http/`, `tests/database/`, and `tests/integration/`, with the
import-boundary check in `tests/test_import_boundary.py`; the example is `examples/sqlite_crud/`;
guides are [HTTP](http.md) and [database](database.md). The Phase 1 follow-up on a configurable
shutdown drain landed as `settings.app.shutdown_timeout`.

**Objective:** prove that the runtime supports a conventional production-style web application before adding Workflow or AI complexity.

**Prerequisites:** Phase 1 readiness/lifecycle and request-scope contracts are complete; the SQLAlchemy Core, `aiosqlite`, and Alembic stack is available through the database extra.

**Work packages**

1. Build a thin ASGI adapter around Starlette. `App` owns the runtime while Starlette owns ASGI routing, request/response types, middleware mechanics, and test client compatibility.
2. Add route decorators and route registration. Inspect handler signatures at registration/validation time, compile explicit injected arguments, and keep ordinary request parameters separate from service injection.
3. Coordinate Starlette lifespan with the runtime. Runtime validation and startup occur before requests are accepted; runtime shutdown executes after the HTTP server stops taking new work.
4. Define middleware order and error behavior. Document the outer-to-inner order, correlation-ID placement, exception normalization, logging, and which errors are safe to expose to a client. Do not silently translate programmer errors into successful responses.
5. Implement the database provider over SQLAlchemy 2.x `AsyncEngine`/`AsyncConnection` and the `sqlite+aiosqlite` dialect: URL/path configuration, connection creation, transaction context manager, explicit migration command integration, health/readiness check, close behavior, and temporary-file test fixture. Do not expose ORM sessions as a required framework abstraction.
6. At database initialization, configure the SQLite connection with foreign keys enabled, WAL mode where compatible, a bounded busy timeout, and an explicit synchronous policy. Set database-level PRAGMAs on connection initialization, not ad hoc inside requests. Keep transactions application-defined and short; do not hold a write transaction across network calls.
7. Build one complete `sqlite_crud` example with an Alembic migration, SQLAlchemy Core table/query definitions, service layer, injected database provider, route-level validation, domain errors, and tests. Exercise SQLite batch migration once in the suite so its table-rebuild behavior is understood before production use.

**Concurrency policy:** SQLite permits a single writer. The provider may retry a small, documented set of transient lock failures only when the operation is safe to retry; it must never hide an indefinitely blocked write. The application database and future durable journal use distinct files and connection pools/configuration.

**Verification and exit criteria**

- The ASGI test client observes that startup completes before a request succeeds and that shutdown releases provider resources.
- CRUD tests cover successful operations, validation failures, missing data, rollback after an exception, and a migration from an empty database.
- Integration tests use a real temporary SQLite file and simulate concurrent writers. Expected outcomes are either bounded success/retry or a documented retryable failure, never a hung test.
- An import-boundary test proves runtime does not import Starlette unless the HTTP adapter is selected, and the database layer does not depend on route/request objects.

**Deliverables:** Starlette adapter, routing/handler injection, middleware/error policy, SQLite provider and migrations integration, CRUD example, test utilities, and database operations guide.

### Phase 3 - trusted plugin and capability model

**Status:** complete. `src/xyberos/plugins/` implements the contract, configuration, and registry;
`src/xyberos/diagnostics.py` reports provider sources and plugin order; the separately packaged
fixture plugin is `tests/fixtures/metrics_plugin/`, the example is `examples/custom_plugin/`, and
the guide is [plugins](plugins.md). The Phase 2 follow-up on provider `source` attribution landed
here: plugin registrations record `plugin:<name>` automatically.

**Objective:** make independently authored, in-process capability integrations predictable without turning the registry into a global service locator.

**Prerequisites:** Phase 1 registry and lifecycle behavior are stable; Phase 2 supplies an HTTP capability as a real plugin consumer.

**Work packages**

1. Define a versioned plugin protocol with immutable name, plugin API compatibility range, declared capability dependencies, optional typed configuration schema, `register`, optional async `start`, and optional async `stop`.
2. Implement an explicit `app.add_plugin(plugin)` path. In the first release, application code chooses plugins directly; defer package entry-point discovery so startup remains visible and reproducible.
3. Add plugin dependency ordering and diagnostics. A failure identifies plugin name/version, lifecycle phase, capability/setting involved, and the original exception chain with secrets redacted.
4. Define provider replacement behavior. Production duplicate registration fails; a named replacement is permitted only by configuration or a test override. Record the source of the active provider in diagnostics.
5. Allow plugins to register routes only through the HTTP adapter contract, and prevent route mutation after readiness.
6. Create a fixture package representing a separately distributed plugin. Test installation, compatibility rejection, duplicate name/provider failures, configuration failures, partial startup cleanup, and route contribution.

**Security boundary:** plugins are trusted arbitrary Python code. Document this in the API and do not imply a sandbox, permission model, or safe execution of untrusted package code.

**Verification and exit criteria**

- A separately packaged plugin supplies a service and optional route to an app without importing undocumented runtime internals.
- Plugin order is deterministic and a dependent plugin cannot start before its requirements are ready.
- Replacement and test override precedence are visible in a diagnostic command/result.
- Compatibility tests reject a plugin built for an incompatible plugin API version before startup work begins.

**Deliverables:** plugin protocol/API, lifecycle integration, custom-plugin example, plugin test fixture package, compatibility guide, and diagnostics output.

### Phase 4 - stable, in-process Workflow engine

**Objective:** provide explicit, inspectable multi-step execution with no persistence or recovery promises.

**Prerequisites:** Phase 1 context and error conventions are stable. A deterministic fake external-service provider is available as a test double; it does not require the Phase 5 public AI facade.

**Work packages**

1. Define immutable `Workflow`, `Step`, `Edge`, input/output contract, retry policy, backoff policy, timeout policy, cancellation token, execution context, event format, and result/error models.
2. Implement build-time graph validation: unique IDs, legal entry/exit nodes, no unsupported cycles, valid branch targets, compatible declared inputs/outputs, and serializable definition metadata. Start with sequential execution plus conditional branch edges; do not claim arbitrary DAG parallelism.
3. Implement execution using structured concurrency. The executor owns every task it creates and awaits/cancels it before returning. A step gets an explicit input, execution context, and deadline.
4. Implement bounded retries. Retry classification must be policy driven; preserve each attempt's outcome; calculate backoff from an injectable clock/random source; stop retrying on cancellation or overall deadline expiry.
5. Implement step and whole-workflow deadlines. Cancellation is cooperative. Detect/block documentation for synchronous CPU-bound or blocking I/O step functions, and provide a deliberate future executor boundary rather than unsafe forced thread termination.
6. Emit structured execution events for started, succeeded, failed, retried, skipped, timed-out, and cancelled states. Integrate trace/correlation metadata without storing sensitive input/output by default.
7. Add a Workflow inspection representation suitable for logs, tests, and documentation. It should display nodes, edges, policies, and definition version without executing handlers.

**Required semantics**

- A step’s side effect may occur more than once when a retry policy applies; callers own idempotency for side-effecting steps.
- Cancellation requested before a next step starts prevents that step from starting. Cancellation of an already-running operation is best effort and depends on the operation cooperating.
- The executor does not retain execution state after process termination. Do not reuse Workflow events as a durable journal.

**Verification and exit criteria**

- Tests deterministically cover order, branching, invalid definitions, retry limits/classification/backoff, step deadline, workflow deadline, cancellation before/during a step, error chaining, and event sequencing.
- Tests assert the executor has no child task still running after success, failure, timeout, or cancellation.
- A fake provider simulates latency, rate-limit errors, transient failures, malformed results, and a cancellation-aware call.
- Workflow documentation clearly distinguishes direct calls, Workflow execution, and experimental durable execution.

**Deliverables:** Workflow builder/executor, policies/models, event/tracing contract, graph inspection, Workflow example, deterministic fake provider, and stable Workflow API documentation.

### Phase 5 - optional AI facade

**Objective:** add model capabilities as adapters that use core runtime and Workflow interfaces but do not shape either one.

**Prerequisites:** Phase 3 provider/plugin conventions and Phase 4 error, deadline, cancellation, and tracing semantics are complete. Ollama is the first supported provider; its adapter is tested against a mocked HTTP API and, separately, a pinned supported Ollama release in opt-in integration tests.

**Work packages**

1. Define provider-neutral protocols for chat/text generation, embeddings, structured output, and optional tool invocation. Normalize request metadata, timeouts, usage, model identity, provider errors, and cancellation signals.
2. Implement a deterministic fake provider first. It supports scripted responses, structured-output failures, token/usage data, delay, rate limit, transient fault, and cancellation tests without network access.
3. Add `xyberos[ollama]` as the first provider adapter. Call the documented Ollama HTTP API through an internal async client; keep Ollama request/response models entirely inside the adapter. Configure `base_url`, required model, timeout, streaming, and optional request options through the typed TOML/environment schema. Do not auto-pull models or make Ollama a core dependency.
4. Implement structured output validation at the facade boundary. Distinguish provider transport failure, refusal, invalid provider payload, and schema validation failure so retry policy can make correct decisions.
5. Define a tool contract with explicit registration and allowlists. Tool invocations need input validation, deadline/cancellation propagation, audit events, and no implicit access to every registered app service.
6. Add Ollama embeddings and streaming chat, then validate the adapter's behavior for models that do and do not support tool calls or schema-constrained output. Defer knowledge/retrieval until its own storage, chunking, filtering, authorization, and evaluation contracts are designed.
7. Build an AI assistant example that runs entirely against the fake provider in CI and offers an explicitly configured Ollama profile for local use. Ollama-backed smoke tests are opt-in, never download models automatically, and keep prompts/responses out of CI logs.

**Security and operations policy:** never log API keys; default to metadata-only request logging; make prompt/response capture an explicit, redacted opt-in; document tool permissions and provider data-handling implications.

**Verification and exit criteria**

- Core package imports and tests pass with no AI SDK installed.
- Fake-provider tests cover timeouts, cancellation, malformed JSON/structured output, tool validation, provider errors, usage accounting, and error redaction.
- The Ollama adapter has request-shape, streaming, embedding, structured-output, tool-capability, and error-mapping tests; live service tests are separately marked and never required for normal CI.
- The AI example uses the same DI, plugin, and Workflow contracts as other services.

**Deliverables:** optional AI package, provider-neutral contracts, fake provider, selected adapters, structured-output/tool APIs, assistant example, and AI security/operations documentation.

**Shipped.** The facade, contracts, tool contract, closed schema subset, and fake provider live in
`src/xyberos/ai/` and import nothing outside the core package and the standard library, so the core
wheel answers "no AI SDK installed" with a working, fully testable facade; `xyberos.ai.ollama` is
the only module behind the `ollama` extra, and `xyberos.ai` never imports it. The frozen contract,
including the classification-is-the-retry-interface rule and the closed schema subset, is
[ADR 0010](adr/0010-ai-facade-contract.md), and `docs/ai.md` carries the guide plus the
security/operations policy with real captured log output.

Two scope notes, both deliberate:

- **Knowledge/retrieval was not built**, as work package 6 requires; it stays in the deferred
  backlog until it has its own storage, chunking, filtering, authorization, and evaluation
  contracts. `PLAN.md` section 4.5 lists it as an initial interface, so it is named there as
  deferred rather than quietly dropped.
- **Model capability claims are declared, not inferred.** The Ollama adapter cross-checks a declared
  `tools` claim against what the model reports through `/api/show`, because that is the only
  capability the API exposes; every other claim is the operator's to make.

Phase 5 also produced the next phase's inputs: AI usage metadata is the only thing Phase 6 may
persist, the event shape is metadata-only by default, and the Ollama release range and smoke-test
model names remain owner decisions.

### Phase 6 - experimental single-host durable executor

**Objective:** provide opt-in persisted Workflow progress for a carefully bounded SQLite, single-host deployment model.

**Prerequisites:** stable Workflow definition/policy/event schemas have versioning; migration tooling, temporary-file test fixtures, monotonic clock abstraction, and process-kill test harness are available. The durable package remains optional and its migrations use a separate journal database.

**Work packages**

1. Write a formal transition table and invariants before implementing workers. Specify every legal source/target state, terminal-state rules, retry scheduling, cancellation races, timeout behavior, lease expiry, worker recovery, and workflow-version incompatibility outcome.
2. Define journal schema and migrations: workflow definitions, executions, step attempts/results, ordered events, worker leases/fencing tokens, scheduled retries, and migration metadata. Include schema and workflow definition version fields in persisted records.
3. Implement execution submission transactionally: persist a known workflow definition/version, validate serializable input and payload size/redaction rules, create `PENDING` execution/event records, and expose read-only inspection.
4. Implement atomic claims with short SQLite transactions. A claim assigns worker identity, monotonic fencing token, and lease expiry. Every heartbeat, result, transition, retry, or cancellation-sensitive update has a conditional `WHERE` clause on current ownership and fencing token.
5. Implement the single worker loop: wake eligible pending/retrying work, claim, execute one permitted step through an activity boundary, persist result/transition, schedule retry, and release/renew lease. Define bounded polling/backoff and resource limits.
6. Implement cancellation. Persist the request first; prevent unstarted steps; signal running cooperative work; record final state only when the current worker has the valid fence. A cancellation request must not let a stale worker mark completed afterward.
7. Implement startup recovery: inspect expired leases/non-terminal executions, acquire a new fenced claim, and decide whether to resume, retry, reconcile, fail safely, or report incompatible definition. Recovery decisions become events.
8. Implement activity idempotency/reconciliation contracts. A side-effecting activity must accept an idempotency key or register a reconciliation operation. Surface `outcome_unknown` when a crash occurs after an external call but before result persistence.
9. Add durable inspection and operational diagnostics: execution status, event timeline, blocked/incompatible work, queue depth, lease age, worker liveness, journal schema version, and explicit experimental/single-host warnings.
10. Mark the experimental surface. Expose the durable API under the experimental boundary, emit `ExperimentalWarning` from unstable entry points, and state the single-host, at-least-once, and no-exactly-once limits in the API docs and package metadata. This discharges the ADR 0003 consequence that experimental APIs are clearly named, documented, and warned about.

**Explicit non-guarantees:** no multi-host ownership, quorum, HA, distributed locks, exactly-once external effects, arbitrary Python checkpointing, transparent replay, or recovery of non-idempotent side effects without a supplied policy.

**Verification and exit criteria**

- Unit tests exercise every state-transition-table row and verify illegal transitions cannot be persisted.
- SQL/integration tests prove atomic claim behavior, contention handling, stale-fence rejection, retry scheduling, lease expiry, cancellation races, and schema/version rejection using a real SQLite file.
- Controlled subprocess termination tests cover crash before start, during activity, after result write, before final transition, and during lease renewal. Restart results must match the documented policy.
- A side-effect simulation proves at-least-once behavior and demonstrates idempotency/reconciliation or `outcome_unknown`, never an unsupported exactly-once claim.
- Documentation provides backup/restore, journal growth/retention, supported deployment topology, incident triage, and data sensitivity guidance.
- Experimental labelling is verified: unstable entry points emit `ExperimentalWarning`, the experimental namespace is used, and package metadata and docs state the single-host and at-least-once limits.

**Deliverables:** optional durable package, schema/migrations, store, scheduler/worker/recovery components, process-fault test harness, durable-workflow example, operator guide, and experimental API label with `ExperimentalWarning`.

**Shipped.** All ten work packages are implemented. The transition table and invariants are frozen in
[ADR 0011](adr/0011-durable-executor-contract.md) and locked by a test that lists every row; the
journal owns a versioned schema in a separate file and refuses one written by a newer package; the
store submits transactionally, claims atomically under a monotonic fencing token, and guards every
write with ownership and the token; a pure scheduler re-derives the next step from persisted state
alone; a worker advances one step per claim, heartbeats its lease, and turns a persisted cancellation
request into cooperative cancellation; recovery resumes what it can prove, retries only what a step
declares idempotent, asks a reconciler when one exists, and parks everything else as
`outcome_unknown`. `docs/durable.md` is the operator guide and `examples/durable_workflow/` shows both
crash cases.

The exit gate is met: `tests/durable/` covers every transition-table row, atomic claims, contention,
stale-fence rejection, retry scheduling, lease expiry, cancellation races, and schema/version
rejection against a real SQLite file; `tests/crash_recovery/` kills a real subprocess at each of the
five documented boundaries and asserts the documented policy in the parent; a side-effect log proves
at-least-once behavior and shows reconciliation resolving an uncertain attempt without a repeat; and
the experimental labelling is verified by emitting `ExperimentalWarning` from `open_journal` and
`DurableWorker`.

Two decisions taken while implementing are worth naming, because they define the contract's edges: a
ready execution belongs to nobody (a live lease protects `RUNNING` work only, so one worker advances
one step per claim and yields), and an unresolved attempt is never handed out as work (the scheduler
reports `NEEDS_DECISION`, so a resumed-but-unreconciled execution parks again instead of silently
repeating an effect).

**Deliberate non-guarantee:** the single-host, at-least-once limits are stated in the guide, the ADR,
the package docstring, and the emitted warning. Phase 7 decides whether to promote or omit, and must
not represent durability as exactly-once, multi-host, or highly available.

### Phase 7 - developer experience, hardening, and release

**Status:** work complete; the release decision itself is the project owner's. All seven work packages
are done: the surface is audited and frozen, the cross-cutting guides and the hello app example are
published, the CLI exists, the release engineering and the resource baselines are in place, and the
threat and abuse review is complete with its two findings fixed. The ADR consequence lists were
walked: every item is satisfied, owned by a named phase, or in the standing deferred backlog. What
remains is a go/no-go decision, and no artefact is published before it.

**Objective:** turn validated features into a release that users can install, understand, upgrade, and operate safely.

**Prerequisites:** stable scope is feature complete (Phases 0-5) and durable capabilities are either explicitly experimental or omitted from the release if their exit gate is not met.

**Work packages**

1. Audit the public API and freeze the stable surface. Add deprecation mechanics, semantic-versioning rules, supported-version policy, and compatibility tests for public imports, configuration fields, plugin protocol, and serialized Workflow definition metadata. **Done:** `docs/stability.md` states the tiers to users, [ADR 0013](adr/0013-stable-surface-and-versioning.md) records the rules, `src/xyberos/deprecation.py` provides the mechanics, and `tests/test_public_surface.py`, `tests/test_compatibility.py`, and `tests/test_deprecation.py` pin it. The audit's finding was the argument for doing it: five documented modules leaked their imports (`Mapping`, `json`, `sys`) as public surface because they declared no `__all__`.
2. Complete documentation: getting started, runtime/DI, configuration, lifecycle, HTTP, SQLite, plugins, Workflow, AI, testing, migrations, error troubleshooting, security considerations, and a separate durable-execution limitations/operator guide. **Done:** each subsystem already had a guide, and this package added the four cross-cutting ones — [getting started](getting-started.md), [testing](testing.md), [troubleshooting](troubleshooting.md), and [security](security.md). Writing them found two documentation defects in `docs/runtime.md` that had survived five phases: `App.resolve` was documented as synchronous when it is a coroutine, and the settings were named as attributes of `App` when they live on `app.settings.app`. Both are corrected, because a guide that names an API that does not exist is worse than no guide. Two further documents were added afterwards for the two audiences a guide set tends to miss: [the tutorial](tutorial.md), whose every output block is produced by running the code it belongs to and is checked by `tests/integration/test_tutorial.py`, and [the architecture review](architecture.md), which is the reviewer's entry point to the design.
3. Finish minimal CLI commands only where they wrap proven APIs: project scaffold, development server, configuration validation/diagnostics, and migrations. Avoid making the CLI a second runtime implementation. **Done:** `src/xyberos/cli/` provides `check`, `new`, `run`, and `migrate` on `argparse` alone. `check` calls `Settings.load` and `App.validate()` and compiles route handlers through the adapter when the extra is installed; `run` hands an import string to the ASGI server so reloading stays the server's job; `migrate` calls `run_migrations`/`apply_migrations` and redacts a password in the URL. Nothing is imported on the application's behalf except in `check`, which starts nothing.
4. Publish tested examples: hello app, SQLite CRUD, custom plugin, Workflow with retry/branch, AI assistant using fake provider, and durable workflow with its limitations displayed prominently. **Done:** `examples/hello_app/` completes the set, and every example is exercised by `tests/integration/`, so an example that stops working fails the suite rather than being discovered by a reader.
5. Add release engineering: changelog, release notes, signed/tagged artifacts as appropriate, SBOM/dependency license audit, vulnerability response policy, wheel/sdist checks, clean-install smoke test, and rollback/release instructions. **Done:** `CHANGELOG.md` (Keep a Changelog, `Unreleased` becoming `2.0.0`), `SECURITY.md` (the vulnerability response policy), `docs/release.md` (the procedure, the dependency and licence audit computed from installed metadata, and the rollback instructions), `tests/test_release_artefacts.py` (the wheel and sdist checks, which build the artefacts rather than trusting the checkout), and a CI job that installs the built wheel into a fresh environment and exercises the CLI from it.
6. Run performance and resource smoke tests. Establish only modest, reproducible baselines for app startup, simple route latency, Workflow overhead, SQLite contention behavior, and durable journal throughput. Treat regressions as signals for investigation, not premature optimization targets. **Done:** `tests/perf/` measures all five, prints one table, and asserts ceilings an order of magnitude above the recorded numbers so a slow machine does not fail the suite. `docs/performance.md` records the baseline, what each measurement includes, and what has deliberately not been optimized.
7. Conduct a final threat/abuse review covering secret handling, configuration diagnostics, provider/plugin trust, tool allowlists, SQL/path input handling, journal payload retention, and logging redaction. **Done:** all seven areas were reviewed against the code rather than the docstrings, and six came back clean with evidence — SQL is built from static strings and bound parameters (the f-string fragments in `durable/store.py` and the PRAGMA interpolation use framework constants and allowlists), the tool set is the allowlist with schema-validated arguments and a container-free context, durable fencing re-states owner/fence/expiry in every conditional write, and `max_payload_bytes` is enforced on every persisted field. Two defects were found in secret handling and both are fixed: a database URL containing `%` crashed Alembic's configuration with the whole URL — password included — in the message, and a rejected Ollama `base_url` echoed a credential it carried when the scheme was also wrong. Regression tests live in `tests/database/test_migrations.py`, `tests/cli/test_cli.py`, and `tests/ai/test_ollama.py`.

**Release decision gate**

| Release area | Required evidence | Where it is |
| --- | --- | --- |
| Core runtime | Lifecycle/DI/configuration tests, clean install, docs examples, supported-version CI | `tests/runtime/`, `tests/contracts/`, `tests/integration/test_hello_app.py`, the `quality` matrix on 3.10–3.13, the `installed-artefact` job |
| HTTP and SQLite | CRUD integration suite, migration test, contention policy test, documented deployment limits | `tests/http/`, `tests/database/`, `tests/integration/test_sqlite_crud.py`, `tests/database/test_migrations.py`, the contention baseline in `tests/perf/`, [database guide](database.md) |
| Plugins | Independent fixture-plugin compatibility suite and versioning documentation | `tests/fixtures/metrics_plugin/`, `tests/integration/test_plugin_packages.py`, `tests/plugins/`, [plugin guide](plugins.md) |
| Workflow | Deterministic behavior suite for validation, retries, cancellation, deadlines, and events | `tests/workflow/`, `tests/contracts/examples/phase4_workflow.py`, [workflow guide](workflow.md) |
| AI | Core-without-AI install, fake-provider suite, redaction/tool tests, adapter contract tests | `tests/ai/`, `tests/integration/test_ai_assistant.py`, the core-only smoke steps in the `optional-installation` job, [AI guide](ai.md) |
| Durable (experimental) | Fault/restart suite, state/lease tests, limitations/operator documentation | `tests/durable/`, `tests/crash_recovery/` (17 process-kill tests), `tests/integration/test_durable_example.py`, [durable guide](durable.md), [performance baselines](performance.md) |

Two rows are decisions rather than evidence lists:

- **Durable execution ships experimental.** Its exit gate is met — that is why it is in the release at
  all — but the promotion evidence in `PLAN.md` section 5.4 is not, so the label stays and the API
  keeps warning.
- **The extra can be omitted instead.** Nothing in the stable tier depends on it, and the
  `optional-installation` job tests every extra in isolation, so a release without durability is a
  supported configuration rather than a diminished one.

**Deliverables:** release candidate, versioned docs, tested examples/templates, changelog/release notes, CI evidence, and a go/no-go checklist signed off by the project owner. Concretely: the release
candidate is the `python -m build` output at the tagged commit, the versioned docs are `docs/` at that
tag ([stability](stability.md) and [release](release.md) included), the examples are the eight under
`examples/` — each exercised by `tests/integration/` — the changelog is [`CHANGELOG.md`](../CHANGELOG.md),
the evidence is the `quality`, `installed-artefact`, and `optional-installation` jobs, and the
procedure that ties them together is [the release guide](release.md).

### Phase 8 - boundary legibility and extension points

**Objective:** make the limits of the framework *legible and actionable* rather than discovered, without
growing core. Phase 7 ended with a list of things Xyberos is a poor fit for; leaving them as an
unexplained absence is what loses a reader, and fixing them by adding features is what loses the
project's reason to exist.

**Prerequisites:** Phase 7 complete, so the surface, the docs, and the release procedure are frozen
enough that a new document is a claim about something stable.

**Work packages**

1. **Record the refusals as decisions.** [ADR 0014](adr/0014-no-identity-or-authorization-model.md)
   (no identity, tenancy, or authorization, plus the sanctioned explicit-principal shape),
   [ADR 0015](adr/0015-durability-is-single-host.md) (single-host durability, with the worker role as
   the integration point and the alternatives named), and
   [ADR 0016](adr/0016-database-providers-are-an-extension-point.md) (one provider shipped, the contract
   reusable). Each records why, and what to do instead.
2. **Publish the positioning page.** [`docs/positioning.md`](positioning.md): who it is for and who it
   is not for, the "if you need X, use Y" table, supported topologies, the capacity summary, and the
   table of defaults with the seam that replaces each one. This is the cheapest artifact in the phase
   and the one that protects the most: it stops wrong adopters arriving.
3. **Make the database provider contract reusable.** `assert_provider_contract` ships in
   `xyberos.database.testing` (preview tier, extra-gated, so core is untouched); the shipped SQLite
   provider runs it in `tests/database/test_provider_contract.py`, which also proves the suite *fails*
   for two deliberately broken providers — one that commits rolled-back work, one whose `retrying`
   drops the operation's result. [`docs/database-providers.md`](database-providers.md) is the author
   guide, including what stays SQLite-specific.
4. **Publish capacity guidance with measured numbers.** A write-throughput scenario joined
   `tests/perf/`, and [`docs/performance.md`](performance.md#capacity-where-the-wall-is) states the two
   findings: about 2 000 writes per second from one writer, and the counter-intuitive one — under
   contention the retry backoff, not the disk, sets the pace.
5. **Ship the two highest-demand integrations as tested recipes.**
   [`examples/tenancy/`](../examples/tenancy/README.md) proves that a payload claiming another tenant
   changes nothing and that an unsigned assertion is refused;
   [`examples/broker_worker/`](../examples/broker_worker/README.md) proves that a redelivered item
   reuses its execution instead of repeating its effects. Both are asserted by
   `tests/integration/`, so a recipe that stops being true fails the suite.
6. **Make extensions visible without discovery.** The [plugin guide](plugins.md#the-catalogue) now has a
   catalogue section: what known extensions exist (none published yet), the four rules a plugin must
   follow, the package layout, and how to be listed. Discovery stays absent by decision
   ([ADR 0007](adr/0007-trusted-plugins.md)); visibility was the actual gap.

**Exit gate**

| Criterion | Evidence |
| --- | --- |
| Every poor fit has a recorded disposition | three ADRs and the positioning page; none is left as an unexplained absence |
| The database seam is proven, not asserted | `assert_provider_contract` passes for SQLite and fails for two broken providers |
| Capacity is a number, not a vibe | the write-throughput baseline in `tests/perf/`, quoted in two documents |
| The integrations that matter are tested code | `tests/integration/test_tenancy_example.py`, `tests/integration/test_broker_worker_example.py` |
| Core did not grow | no change to `src/xyberos/__init__.py`, the runtime, or the core dependency set; the one new public name lives in the `database` extra's testing module |

**Deliverables:** three ADRs, three documents (positioning, database providers, and the capacity
section), one reusable conformance suite, and two tested examples — all of it outside the runtime.

## Cross-phase controls

### Dependency and import boundaries

```text
core runtime/config/registry
        |
        +-- HTTP adapter -- SQLite application provider
        |
        +-- plugin protocol
        |
        +-- Workflow
        |
        +-- AI facade (core, no SDK) -- AI adapters (optional)
        |
        +-- durable executor (optional, separate journal)
```

Dependencies point downward in this diagram, and optional pieces hang off the core rather than off
each other. The runtime cannot import HTTP, AI, or durable modules; `xyberos.ai` imports neither a
vendor adapter nor `xyberos.execution`, so an AI call is usable with or without a workflow around it;
Workflow cannot import a particular AI SDK; and the durable executor consumes stable Workflow
definition contracts without replacing the in-process executor for ordinary work. The one dependency
between optional packages is deliberate and narrow: `xyberos.durable` imports the SQLite connection
plumbing in `xyberos.database.sqlite` for PRAGMAs, WAL, and the bounded retry on write contention,
while keeping its own file, schema, and tables. Building a second copy of that plumbing was rejected
as the larger risk.

### Definition of phase completion

A phase is complete only when its documented public API, tests, examples, operational constraints, and exit gate are present. A demo, passing happy-path test, or unreviewed internal module is not completion. New work discovered during a phase belongs in one of three places: required to satisfy the accepted exit gate, a documented later-phase dependency, or the deferred backlog.

### Delivery cadence

At the end of each phase, conduct a short design and operational review: confirm import boundaries, run the phase exit suite from a clean environment, update ADRs/docs, walk the ADR consequence lists and confirm each item is satisfied, owned by a named phase, or in the deferred backlog, review public error messages and redaction, and decide whether the next public contract is ready to freeze. This makes the 10-18+ week estimate in `PLAN.md` measurable rather than calendar-only.

## First implementation contracts

These are the target shapes for the public API. Every one is implemented and executed by a contract
test rather than only documented: the runtime portion by
`tests/contracts/examples/phase1_minimal_app.py`, the routed handler by
`tests/contracts/examples/phase2_http_app.py`, and the Workflow builder by
`tests/contracts/examples/phase4_workflow.py`.

```python
from typing import Annotated
from xyberos import App, Inject

app = App()
app.provide(UserService, factory=UserService, scope="app")

@app.get("/users")
async def list_users(users: Annotated[UserService, Inject()]) -> list[User]:
    return await users.list_users()
```

`provide` should reject ambiguous registrations. `Inject()` is required for handler injection; the type annotation identifies the contract. Runtime validation reports a path such as `UserService -> DatabaseProvider` when resolution fails. Test overrides are scoped to an app or test context and must never mutate another `App` instance.

```python
workflow = (
    Workflow("support", version="1")
    .step("retrieve", retrieve_documents, retry=Retry(max_attempts=3))
    .step("answer", generate_answer, timeout=seconds(30))
    .edge("retrieve", "answer")
)
result = await workflow.run(input=request_data, timeout=seconds(45))
```

The initial Workflow state is an explicit input/result mapping, not mutable ambient state. Step functions receive only their declared input and an execution context containing cancellation/deadline/tracing facilities. Workflow definitions and policies are immutable after validation.

Two clarifications the implementation made explicit, both recorded in
[ADR 0009](adr/0009-workflow-engine-contract.md): public policies take *durations* while the
execution context exposes the derived absolute deadline, and a step's `timeout` bounds one attempt
rather than the whole step, so a retried step gets a fresh timeout each time.

## Durable executor state and storage requirements

Implement and test the transition table before writing a worker loop. At minimum, terminal states are `COMPLETED`, `FAILED`, `CANCELLED`, and `TIMED_OUT`; non-terminal states are `PENDING`, `RUNNING`, `RETRYING`, and `WAITING`. Every transition records event sequence, timestamp, reason, worker/lease identity when relevant, and a schema version.

Use a journal database such as `xyberos_journal.db`, distinct from `app.db`. On initialization, apply migrations and configure WAL, a bounded busy timeout, and a documented synchronous setting. Perform claims with a single conditional transaction; retain a lease token and require it in every completion, retry, heartbeat, and cancellation-sensitive update. Store payload/result references with size limits and redaction rules rather than unbounded sensitive JSON.

Recovery must be intentionally at-least-once for activities unless an activity provides idempotency/reconciliation. Each activity contract must state its idempotency key or its recovery policy. A restart test must cover crash-before-start, crash-after-result-persisted, crash-during-activity, expired lease, and cancellation race.

## Test and quality strategy

| Layer | Mandatory checks |
| --- | --- |
| Unit | Dependency graph/scopes, lifecycle order, config precedence, graph validation, policies, state transitions. |
| Integration | ASGI lifespan/routes, SQLite transactions and write contention, plugins, Workflow cancellation and timeouts, optional extras. |
| Fault injection | Provider startup failure, transaction lock/error, Workflow step failure, stale lease, controlled worker termination. |
| Packaging | Build wheel/sdist, clean install of core and each extra, public-import audit, supported Python matrix. |
| Static quality | Formatting, linting, strict type checking for public contracts, dependency audit, and documentation example tests. |

Use a monotonic clock abstraction for Workflow and durability tests. Avoid sleep-based timing assertions. Use a real temporary SQLite file, rather than only in-memory SQLite, for WAL, locking, migration, and restart coverage.

## Backlog deliberately deferred

- Distributed workers, multi-host coordination, and HA scheduling.
- Exactly-once effects, transparent replay, and arbitrary workflow code recovery.
- A custom ORM, migration engine, task queue, or plugin sandbox.
- Automatic plugin discovery, arbitrary third-party plugin isolation, and large project-generation CLI features.
- A step-executor boundary that can stop blocking work, such as process or thread isolation with
  real cancellation. Phase 4 rejects synchronous step functions and documents
  `asyncio.to_thread(...)` as the interim answer instead of force-terminating threads.
- A timeout policy object in place of the scalar `Step.timeout`, and a richer `input_type`
  contract than an `isinstance`-checked class, both deferred by
  [ADR 0009](adr/0009-workflow-engine-contract.md).
- Static analysis that proves branches merging into one step are mutually exclusive; Phase 4 fails
  such a merge at runtime instead.
- Parallel step execution and any claim of DAG scheduling; Phase 4 is sequential and conditional by
  design.
- Dynamic/imperative decorator Workflows until declarative Workflow semantics and introspection are stable.
- Knowledge/RAG subsystem until it has a bounded, independently useful provider contract; Phase 5
  ships embeddings and a tool allowlist, which is what a retrieval layer would need, but no
  storage/chunking/filtering/authorization contract is designed yet.
- Deriving tool schemas from type annotations, instead of requiring an explicit schema per tool
  ([ADR 0010](adr/0010-ai-facade-contract.md)).
- Streaming tool calls: a streaming response carries content only, and partially validated
  structured output is not actionable. Supporting this needs a new ADR, not a patch.
- Additional JSON Schema keywords (`oneOf`, `$ref`, `pattern`, numeric exclusivity). The subset is
  closed by decision, so widening it requires a new ADR rather than passing a schema that would
  validate more loosely than it reads.
- Pairing an embedding model with a chat model in a single provider contract; Phase 5 configures
  them separately (`model`, `embedding_model`) because one Ollama model does not serve both.
- Structural validation of a reconciler's returned output. The journal checks that a result is
  JSON-serializable and bounded, not that it matches the shape downstream steps expect; Phase 6
  documents the trap and shows the pattern to copy, and a real check would need the definition to
  declare a step's output type.
- Journal retention tooling: Phase 6 documents how to bound the file (delete terminal executions,
  which cascades) and deliberately ships no scheduler or command for it.
- Promoting durable execution beyond experimental status. `PLAN.md` section 5.4 lists what has to be
  demonstrated; until then the API keeps warning.

**Non-goals, not deferred work.** Xyberos does not infer a refusal, a provider capability, or
structured-output support from response text. Only a provider-reported signal is trusted, because a
guess presented as a classification is worse than an absent one.

The disposition of the external review proposals — including the deferred decorator Workflow API and
the rejected reordering of the AI facade — is recorded in `PLAN.md` Appendix A.

## Remaining owner decisions

The license was the last Phase 0 blocker. **Decided:** the project is licensed under **Apache-2.0**
([ADR 0012](adr/0012-project-licence.md)), declared in `pyproject.toml` through PEP 639 metadata and
shipped as `LICENSE`. The adopted Python, database, TOML, Ollama, and versioning decisions remove the
rest.

**Decided for the AI surface.** These were the "before the relevant delivery phase begins" items, and
they are now settled rather than pending. Each is recorded where a reader will look for it, and each
is either enforced in code or stated as a policy:

| Decision | Value | Enforced by |
| --- | --- | --- |
| Supported Ollama release range | **≥ 0.5.0** | `MINIMUM_SUPPORTED_VERSION` in `src/xyberos/ai/ollama.py`; the adapter reports an older service as unhealthy and refuses later requests with the reason. Lowering it requires an explicit `minimum_version` setting |
| Smoke-test chat model | `llama3.2:3b` (~1.9 GB), tool-capable | `XYBEROS_OLLAMA_LIVE_MODEL` default in `tests/ai/test_live_ollama.py` |
| Smoke-test embedding model | **none**; the operator names one | `XYBEROS_OLLAMA_LIVE_EMBEDDING_MODEL` has no default, so the embedding tests skip |
| Capability-specific live tests | their own gate | `XYBEROS_OLLAMA_LIVE_TOOLS=1` for tool tests, so a model without tool support skips rather than fails |
| Model download and container policy | never pull, start, stop, upgrade, or deploy anything | `AIModelNotFoundError` names the `ollama pull` command; CI installs no models |
| **AI telemetry retention** | no AI content is persisted by the framework; usage metadata is retained only for as long as the execution that produced it | `LoggingPolicy.metadata_only()` by default; journal retention in [`docs/durable.md`](durable.md) |

**Decided: the release identity.** This line publishes as `xyberos` **`2.0.0`**, because the `xyberos`
name is held on the package index by the already-published 1.x line, which installs the same import
root and cannot be co-installed, so `0.1.0` would be unreachable through a plain `pip install` and
would read as a regression. The leading digit records lineage; maturity is carried by the
`Development Status` classifier and the tiers in [`stability.md`](stability.md). The decision, its
cost, and the trade it makes are in [ADR 0017](adr/0017-release-identity-and-lineage.md); its
procedural consequence is that a version bump touches six files rather than two.

**Still open, and owned by the project owner.** Contributor terms: whether to adopt a DCO, a CLA, or
copyright assignment. Nothing is due today, and the choice is easy to add later: a DCO is a
`CONTRIBUTING.md` line plus a `Signed-off-by:` trailer, and its enforcement is a CI check on the pull
request. A CLA is different in kind — it exists to keep the *option* to relicense, and that option
expires with the first outside contribution, so it cannot be added after the fact. The trigger to
decide is therefore one event, not a date: **settle it before merging the first pull request from
anyone other than the copyright holder** ([ADR 0012](adr/0012-project-licence.md)). Also still
owner-owned: any future promotion of durable execution beyond experimental status, whose criteria are
`PLAN.md` section 5.4. The first upload adds its own owner decisions — index access and the fate of the
documentation site — and they are listed as preconditions in
[the release guide](release.md#preconditions).
