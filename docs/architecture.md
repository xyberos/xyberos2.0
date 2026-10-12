# Xyberos architecture — reviewer's guide

> **How to read this document.** `PLAN.md` is the architecture baseline, the [ADRs](adr/) are the
> decisions of record, and the per-subsystem guides state the contracts users rely on. This page is
> the entry point for an engineer reviewing the design: it explains *why* the pieces are shaped the
> way they are, what was rejected, what the evidence is, and where to push back. If this page ever
> disagrees with an ADR or a guide, they win — and that is a defect in this page worth reporting.

Written at the Phase 8 close, for a reviewer who has not read anything else. This line publishes as
`2.0.0` ([ADR 0017](adr/0017-release-identity-and-lineage.md)).

## 1. What it is, and what it refuses to be

Xyberos is a composable Python application runtime. An application is composed from explicit typed
providers, configured from TOML and the environment, started and stopped through one lifecycle, and
optionally extended with HTTP, SQLite, plugins, workflows, AI, and durable execution.

The design is defined at least as much by refusals as by features:

| Refusal | Consequence |
| --- | --- |
| No service locator | Dependencies are declared in annotations and resolved from the graph; a parameter name never resolves anything |
| No hidden I/O at import | `import xyberos` loads no optional capability, enforced by subprocess tests |
| No bundled server | Xyberos does not implement an ASGI server; Starlette provides the ASGI mechanics and any server runs the result |
| No bundled AI SDK | The facade ships in core and talks the provider's documented HTTP; only adapters sit behind extras |
| No sandbox | Plugins, step functions, and tool handlers are trusted in-process code, stated in the [security guide](security.md) |
| No universal workflow engine | The workflow engine is sequential, declarative, and inspectable; DAG scheduling, loops, and parallel steps are out of scope |
| No distributed durability | Single instance, one journal file, at-least-once effects, experimental — and it says so in an `ExperimentalWarning` |
| No inferred capability | A model's tools/streaming/structured-output support is *declared*, never guessed from response text |

The whole stable tier — runtime, configuration, workflow, plugins, errors — runs on the standard
library alone. `tomli` is the only unconditional dependency, and only below Python 3.11.

## 2. System shape

```text
                        ┌──────────────────────────────────────────┐
                        │  your application code                   │
                        │  (services, handlers, steps, tool        │
                        │   handlers — trusted, in-process)        │
                        └───────────────┬──────────────────────────┘
                                        │ composition + declared annotations
        ┌───────────────────────────────▼───────────────────────────────┐
        │  core runtime            xyberos                              │
        │  App · provider registry · scopes · lifecycle · route records  │
        │  typed configuration · context/logging · error taxonomy        │
        └───┬───────────┬───────────┬───────────┬───────────┬───────────┘
            │           │           │           │           │
     ┌──────▼───┐ ┌─────▼────┐ ┌────▼─────┐ ┌───▼─────┐ ┌───▼──────────┐
     │ plugins  │ │ Workflow │ │ AI facade│ │ HTTP    │ │ durable      │
     │ (core)   │ │ (core)   │ │ (core)   │ │ adapter │ │ executor     │
     └──────────┘ └──────────┘ └────┬─────┘ │ [http]  │ │ [durable]    │
                                    │       └───┬─────┘ └───┬──────────┘
                              ┌─────▼─────┐     │           │
                              │ ollama    │     │           │
                              │ [ollama]  │     │           │
                              └───────────┘     │           │
                                        ┌───────▼───────────▼────────┐
                                        │ SQLite provider [database] │
                                        └────────────────────────────┘
```

The rule is one sentence: **dependencies point down, optional pieces hang off the core, not off each
other.** It is enforced, not aspirational — `tests/test_import_boundary.py` spawns a subprocess per
claim and asserts that importing a layer loads nothing it should not:

- core loads no `starlette`, `sqlalchemy`, `aiosqlite`, `alembic`, or `httpx`;
- the runtime imports no HTTP or database module, and no `xyberos.ai`;
- the AI package imports no provider SDK and no adapter;
- the durable package imports no HTTP and no AI, and *fails with the extra to install* when its own
  dependency is missing.

The single deliberate exception is stated where it is made: `xyberos.durable` imports the SQLite
connection plumbing in `xyberos.database.sqlite` for PRAGMAs, WAL, and the bounded retry on write
contention, while owning its own file, schema, and tables. Writing that plumbing twice was judged the
larger risk.

Three code paths are worth a sequence diagram each, and each exists in one place:

```text
request      CorrelationID → ErrorMapping → RequestScope → your middleware → router
             (binds a correlation ID)  (turns errors into bodies)  (opens the request scope)

startup      register → validate → starting → ready → stopping → stopped
             (graph + annotations)         (eager app-scoped services)   (reverse order, all tried)

durable step claim → run step → commit step result → yield or finish
             (lease + fencing token)  (one crash boundary per commit)
```

## 3. Subsystem contracts

| Subsystem | Module | Contract | Key mechanism | Tier |
| --- | --- | --- | --- | --- |
| Runtime | `xyberos`, `app.py`, `runtime/` | `App`, `Inject`, `Scope`, `LifecycleState` | provider graph validated from annotations; scope lattice enforced | stable |
| Configuration | `config.py` | `Settings`, `AppSettings` | TOML + `XYBEROS_` environment mapping, field-level errors, opaque capability sections | stable |
| Errors | `errors.py` | `XyberosError` root, one family per subsystem | one root so `except XyberosError` is total; refused writes report *which* guard refused | stable |
| Workflow | `execution/` | `Workflow`, `Step`, `Retry`, `WorkflowExecutor` | immutable declarative definition, build-time validation, structured events | stable |
| Plugins | `plugins/` | `Plugin`, `PluginRegistry` | explicit ordered registration, typed config, provider source attribution | stable |
| HTTP | `http/` | `HttpAdapter`, `Route`, `read_json_object` | route records in core compiled by the adapter; handler signatures checked at construction | preview |
| SQLite | `database/` | `DatabaseProvider`, `SqliteSettings` | SQLAlchemy Core, PRAGMAs installed on connect, opt-in bounded retry | preview |
| AI | `ai/` | `AIFacade`, `ModelProvider`, `ToolSet` | declared capabilities, closed schema subset, allowlist, metadata-only logging | preview |
| Durable | `durable/` | `JournalStore`, `DurableWorker` | versioned journal, transition table, fencing tokens, per-step recovery | experimental |
| CLI | `cli/` | the `xyberos` command | thin wrappers: no second runtime | preview |
| Deprecation | `deprecation.py` | `warn_deprecated`, `deprecated` | one message composed from four facts; ships before the first deprecation | stable |

The tiers are promises about change, not quality grades, and are defined in
[the stability guide](stability.md).

## 4. The mechanisms worth reviewing closely

### 4.1 Dependency injection is a validated graph, not a container

Providers are registered against a contract (a class or any hashable key). Dependencies are read from
the factory signature: every required parameter must carry `Annotated[T, Inject()]`. Validation walks
the whole graph before anything is constructed and reports *the resolution path*, so the error names
the chain rather than the leaf:

```text
MissingProviderError: no provider is registered for Repository; required by Service
  path: (Service, Repository)
```

Two properties follow, and both are the point:

- **Name-based injection is impossible by construction.** A parameter without a marker fails
  registration, so there is no lookup that could resolve a different service than the annotation says.
- **A lifetime violation is a startup error.** `Scope` forms a lattice (`app` ≥ `request` ≥
  `transient`) and a longer-lived service may not capture a shorter-lived one. The check is static:
  it fails `validate()`, not the first request that resolves it.

`App.with_overrides()` clones registrations into an independent application for tests. It copies
providers and routes but *not* plugin registrations — a documented asymmetry, because running plugin
lifecycle hooks twice across clones would be worse than not having them.

### 4.2 Route records are dependency-free; the adapter compiles them

`xyberos.Route` is an immutable record. Core never imports Starlette; the adapter compiles records into
endpoints and validates handler signatures when `HttpAdapter(app)` is constructed, so a typo fails at
startup rather than on the first request. Every handler parameter is exactly one of: an injected
dependency, a path parameter from the template, or `Request`. Nothing is invented for a parameter that
cannot be supplied.

Error handling is a policy, not per-route wiring: `HttpError` subclasses carry their status and are
rendered as `{"error": {"type", "message"}}`; anything else becomes a generic `500` with the traceback
logged, never returned. If a response has already started, the failure is re-raised instead of
corrupting the stream.

### 4.3 Workflow: declarative because it has to be inspectable

`Workflow(...)` is an immutable builder. `validate()` compiles the definition into a graph and
rejects cycles, unreachable steps, ambiguous merges, and more than one edge leaving a step — before
execution, with no side effects. Execution is sequential and conditional by design; `render()` shows
what was built, and events are structured facts rather than log lines.

Synchronous step functions are rejected rather than quietly wrapped: a blocking function would stall
the loop and could not be cancelled. The escape hatch is explicit —
`await asyncio.to_thread(...)` inside an async step, accepting that cancellation then cannot stop the
thread.

### 4.4 Durable execution: durability by transaction boundary

The design rule is that **workflow code is never persisted**, so recovery is per *step*, never per
bytecode. Everything else follows:

- The journal is a separate SQLite file with `synchronous=FULL` and a version in `journal_metadata`;
  a journal written by a newer package is refused rather than interpreted.
- Statuses live in a transition table; an illegal transition raises `DurableStateError` rather than
  being written.
- Every write is guarded by `owner` + fencing token + live lease. A refused write is re-read and
  reported as lease, cancellation, or state — never as "no rows matched", which would hide the reason.
- Ready work belongs to nobody; a live lease protects `RUNNING` only. Expiry therefore makes work
  reclaimable *without* invalidating the fencing token, which is why the lease row survives.
- The scheduler is a pure function of persisted state. An attempt whose outcome cannot be established
  is recorded `outcome_unknown` and parked (`PlanKind.NEEDS_DECISION`) — never retried on a guess,
  because retrying an effect of unknown status is the one failure mode that turns a framework into a
  liability.
- A definition fingerprint gates resumption; a changed definition fails the execution as incompatible
  rather than running new code against old state. That fingerprint is pinned by a golden-value test,
  because changing the algorithm invalidates work in someone's journal.

### 4.5 AI: declared capabilities, closed schemas, and an allowlist

The facade is provider-neutral and ships in core; `FakeModelProvider` implements the full provider
contract so every scenario is testable without a service. Three properties are structural:

- **Capabilities are declared, not inferred.** A request needing tools, streaming, embeddings, or
  structured output is refused before any call if the model does not declare it. The one cross-check
  is Ollama `/api/show`, because it is the only capability the API exposes.
- **The schema subset is closed.** The supported JSON Schema keywords are a decision, and widening it
  requires a new ADR rather than accepting a schema that would validate more loosely than it reads.
- **The tool set *is* the allowlist.** Nothing a model returns is executed; a call is resolved against
  the caller's set, validated against the declared schema, then run with a frozen mapping and no
  container. Logging is metadata-only by default; content capture is an explicit opt-in that truncates
  and redacts.

## 5. Configuration, errors, and the CLI as boundaries

**Configuration precedence** is explicit arguments → `XYBEROS_` environment variables → file →
defaults, with `__` for nesting (`XYBEROS_APP__DEBUG=true`). Unknown keys, wrong types, and an
unsupported `schema_version` are rejected with a field-level `ConfigurationError` that names the field
and its source but never echoes a value. Capability sections (`[plugins.*]`, `[ai.*]`) are opaque to
core; the capability validates its own keys.

**The error taxonomy** is one root (`XyberosError`) with per-subsystem families, so a caller can catch
everything this framework raises without catching the world. Two conventions matter more than the
names: every message carries the facts needed to act (field, contract, path, floor, release), and a
refusal is never disguised as an empty result.

**The CLI** wraps APIs the runtime already proves: `check` is `Settings.load` + `App.validate()` +
`App.diagnostics()`, `run` hands an import string to whatever ASGI server is installed, `migrate`
calls the Alembic runner and redacts a password. It is `argparse` from the standard library, and the
promise is the command and its options — not the modules behind them.

## 6. Testing as part of the architecture

The suite is not a safety net bolted on afterwards; several contracts exist *because* they are
testable, and the tests carry security and compatibility weight.

| Surface | Tests | What is actually proven |
| --- | --- | --- |
| `tests/runtime/` | 77 | lifecycle ordering, scope enforcement, isolated instances, overrides |
| `tests/http/` | 24 | handler compilation, middleware order, error bodies, lifespan refusal |
| `tests/database/` | 31 | PRAGMAs, transactions, contention, migration configuration, the provider contract |
| `tests/plugins/` | 29 | ordering, typed config, compatibility, lifecycle failure reporting |
| `tests/workflow/` | 107 | retries, deadlines, cancellation, events, validation — on a virtual clock |
| `tests/ai/` | 133 | facade behaviour, schema subset, tool allowlist, adapter contract, redaction |
| `tests/durable/` | 103 | transitions, journal schema, guarded writes, recovery decisions |
| `tests/crash_recovery/` | 17 | **a real subprocess killed at five boundaries**, then recovery |
| `tests/integration/` | 74 | every example end to end, including the HTTP/DB/plugin/AI/durable paths, the tenancy and broker recipes, and the extension examples the Extend pages walk through |
| `tests/cli/` | 37 | each command, its exit codes, and its refusal messages |
| `tests/perf/` | 7 | startup, latency, workflow overhead, write throughput, contention, journal throughput |
| `tests/site/` | 205 | the documentation site: lesson output, transcripts and scaffolds, links, tier labels, the generated reference, the snippet hook, and the canonical URL one configuration resolves for a preview and for the release |
| `tests/test_public_surface.py` | 84 | the frozen `__all__` of every public module |
| `tests/test_import_boundary.py` | 21 | the layering rules, in subprocesses |
| `tests/test_compatibility.py` | 14 | configuration fields, plugin protocol, golden definition fingerprint |
| `tests/test_release_artefacts.py` | 7 | what the built wheel and sdist must contain |
| `tests/contracts/` and four root modules | 33 | executed API examples, deprecation mechanics, optional-dependency messages, the public API, package import |

991 tests total. Four techniques are worth copying from:

- **Deterministic doubles instead of sleeping.** `ManualClock`, `FakeExternalService`, `Reply`,
  `FakeModelProvider`, `ModelReply`, `ManualWallClock`, `expire_leases`, `temporary_database`. Time and
  failure are inputs, so a retry assertion is exact rather than probabilistic.
- **Fault injection with a real process.** `os._exit` at a documented boundary means cleanup is
  skipped, so only committed state survives — which is the condition being tested. An in-process
  simulation of a crash proves nothing about durability.
- **Import boundaries in subprocesses.** A module already imported by another test would hide a leak,
  so each claim runs in a fresh interpreter.
- **Frozen surfaces with golden values.** Adding or removing a public name is an edit to one file with
  a diff, and changing the definition fingerprint invalidates work in real journals, so it is a
  reviewed change rather than a silent one.

## 7. Decisions of record

| ADR | Decision | What a reviewer should take from it |
| --- | --- | --- |
| [0001](adr/0001-runtime-boundaries.md) | Keep the runtime small and capability-oriented | the boundary that defines what core may do |
| [0002](adr/0002-configuration-and-database-stack.md) | TOML + SQLAlchemy-based SQLite | the choice of stdlib `tomllib` and one database stack |
| [0003](adr/0003-versions-and-experimental-scope.md) | Start at `0.0.0`; isolate experimental scope | why durability warns; its version base is superseded by 0017 |
| [0004](adr/0004-initial-ai-provider.md) | Ollama as the first provider | why an HTTP-speaking local provider, and the version floor |
| [0005](adr/0005-phase-1-runtime-contract.md) | Freeze the Phase 1 runtime contract | the injection and lifecycle guarantees |
| [0006](adr/0006-http-and-database-adapters.md) | HTTP and database behind adapters | why Starlette owns ASGI mechanics |
| [0007](adr/0007-trusted-plugins.md) | Trusted plugins, explicit and ordered | no sandbox, no discovery — and why that is the safer default |
| [0008](adr/0008-workflow-terminology.md) | The unit is a *Workflow* | the rename and its cost |
| [0009](adr/0009-workflow-engine-contract.md) | Freeze the workflow contract | declarative-first, sequential, no persistence claimed |
| [0010](adr/0010-ai-facade-contract.md) | Freeze the AI facade contract | declared capabilities, closed schema subset, allowlist |
| [0011](adr/0011-durable-executor-contract.md) | Freeze the durable contract | per-step recovery, fencing, `outcome_unknown` |
| [0012](adr/0012-project-licence.md) | Apache-2.0 | the patent grant, and the relicensing option that expires with the first outside contribution |
| [0013](adr/0013-stable-surface-and-versioning.md) | Freeze the surface and the versioning rules | what "stable" means, and what happens when a name has to leave it |
| [0014](adr/0014-no-identity-or-authorization-model.md) | No identity, tenancy, or authorization model | why a framework must not pick an authorization model, and the shape to build instead |
| [0015](adr/0015-durability-is-single-host.md) | Durability is single-host | why multi-host is a different product, and how a queue plus the journal covers the middle ground |
| [0016](adr/0016-database-providers-are-an-extension-point.md) | Database providers are an extension point | why one provider ships, and what a conformance suite makes that mean |
| [0017](adr/0017-release-identity-and-lineage.md) | Publish this line as `xyberos` 2.0.0 | why the number is a major one, and why maturity is the classifier's job rather than the version's |

## 8. Trade-offs accepted, and what was rejected

| Decision | Alternative rejected | Why |
| --- | --- | --- |
| Explicit `Annotated[..., Inject()]` dependencies | container-style `__init__(self, repo: Repository)` resolution | magic that resolves by name is undebuggable and cannot be validated statically |
| Validation at composition time | lazy resolution with runtime errors | a misconfigured application should fail before it serves work |
| Starlette for HTTP | a hand-rolled ASGI layer, or FastAPI | Starlette is the mechanics without a second opinionated framework above it |
| Route records in core | importing HTTP types into the runtime | keeps `import xyberos` dependency-free and the runtime testable without a server |
| Declarative workflow builder | decorator/imperative API | arbitrary Python control flow cannot be inspected or recovered; deferred, not rejected forever |
| Sequential, conditional execution | parallel steps / DAG scheduling | concurrency semantics are a contract this project is not ready to promise |
| Separate journal file | reuse the application database | a retrying workflow must not be able to lock the application's tables |
| Versioned journal schema, refuse newer | open and hope | interpreting rows you do not understand is how silent corruption starts |
| Per-step crash boundary | per-bytecode or per-event sourcing | workflow code is never persisted, which is the only honest guarantee available here |
| Park unresolved attempts | retry on a guess | a duplicated external effect is worse than a stalled execution |
| `argparse` for the CLI | Click/Typer | a framework that refuses an HTTP dependency will not add a CLI framework |
| No plugin discovery | `importlib.metadata` entry points | startup stays visible and reproducible; entry-point loading is a supply-chain surface |
| No second database provider in core | shipping Postgres and MySQL alongside SQLite | the provider maintained by the people who need it beats three maintained by people who do not; the conformance suite makes that safe |
| No identity or authorization model | a first-party auth layer | authorization is a product decision, and a partial implementation is the worst option |
| Metadata-only AI logging | logging prompts by default | prompts are where secrets leak, and a default is a policy everyone inherits |

## 9. Limits, and honest gaps

These are stated so a reviewer does not have to discover them:

- **Single instance only.** The journal's coordination is SQLite locking. A network filesystem is
  unsupported, and no claim is made about multi-host execution or high availability.
- **At-least-once effects.** A persisted step result proves the step completed, not that its external
  effect happened exactly once. Idempotency keys are the caller's job.
- **Backup and restore is documented, not automated, and not tested.** Rotation, retention, and a
  restore drill are deployment responsibilities. The retention mechanism the guide describes (delete a
  terminal execution; the schema cascades to steps, events, lease, and retry) is real but unproven by
  a test.
- **Durable execution is experimental** and will warn. Its promotion criteria are `PLAN.md` §5.4; six
  of eight are met by executable evidence, and the two that are not are the backup/restore procedure
  and the bounded-consumption claim.
- **The store is the largest module in the project** (`durable/store.py`, ~1 730 lines). Every guarded
  write shares one explanation path, which is why the invariants live together — but whether that
  stays true is a fair review question, not a settled decision.
- **Two of the five poor fits are permanent, not pending.** "Batteries included" and host-spanning
  durability are different products. [The positioning page](positioning.md) says which alternative to
  reach for, and the ADRs record why; nothing here is waiting on a phase to finish.
- **No authorization model, no sandbox, no secret manager, no TLS, no request size or rate limits.**
  Each is documented as belonging to the deployment; the [security guide](security.md) lists them under
  "what is not protected here".
- **No performance claim beyond the baselines.** [performance.md](performance.md) records numbers from
  one machine for comparison against themselves. Nothing has been optimized.
- **The framework is pre-release, on a `2.x` version base.** Until `2.0.0` exists, a minor release may
  break a stable name with upgrade notes; from `2.0.0` that requires a major release, and a minor
  release may break only a preview name. The leading digit records lineage rather than maturity
  ([ADR 0017](adr/0017-release-identity-and-lineage.md)); the tiers and the `4 - Beta` classifier carry
  the maturity claim.

## 10. Where to push back

Questions worth asking in review, in rough order of how much they would change the design:

1. **Is the DI contract right?** Explicit annotations are verbose. Is the verbosity earned by static
   validation, or is it a tax that a lighter convention would beat? (See `runtime/dependencies.py`.)
2. **Does the durable design hold under a real deployment?** The process-kill harness proves restart
   recovery, not a disk that loses a commit or an operator who restores the wrong copy.
3. **Is the store's size a smell?** `durable/store.py` concentrates the write invariants; is that
   cohesion or a future merge conflict?
4. **Is the workflow engine's scope right?** Sequential and conditional covers a lot, but the first
   team that needs a fan-out will ask for parallel steps. Is "no" still the answer under load?
5. **Is the AI facade's capability model sufficient?** Declared capabilities fail fast, but a wrong
   declaration is a configuration bug that only shows up in production.
6. **Are the tiers honest?** `xyberos.ai` is preview even where it is built on stable pieces. Is that
   the right call, or is it over-caution that costs adoption?
7. **Does the CLI belong?** It is thin by construction, but it is still another surface to keep
   compatible.

## 11. Code map

Read in this order to understand the system; the sizes indicate where the mass is.

```text
src/xyberos/                                    10 783 lines over 62 modules
├── app.py                          529   composition root: App, RequestContext, plugins, diagnostics
├── config.py                       287   typed settings, precedence, opaque capability sections
├── errors.py                       435   the taxonomy, one root, eight families
├── routing.py                       97   dependency-free route records
├── deprecation.py                   92   warn_deprecated / deprecated
├── runtime/                        488   registry and graph validation, context, lifecycle state
│   ├── dependencies.py             334   annotation reading, graph + scope validation
│   ├── context.py                  106   contextvars, correlation IDs, ContextLogFilter
│   └── lifecycle.py                 15   the state enum
├── execution/                    2 037   models, policies, validation, executor, events, direct, testing
│   ├── validation.py               337   build-time graph validation
│   ├── executor.py                 669   structured concurrency, retries, deadlines, cancellation
│   └── testing.py                  245   ManualClock, FakeExternalService, Reply
├── durable/                      3 479   the largest subsystem
│   ├── store.py                  1 732   submission, fenced claims, guarded writes, inspection
│   ├── worker.py                   418   one step per claim, lease heartbeat, yield
│   ├── models.py                   367   statuses and the transition table
│   ├── journal.py                  277   versioned schema, DDL in one transaction
│   └── scheduler.py / recovery.py  358   the next action, and what an interrupted attempt means
├── ai/                           2 601   facade, contracts, closed schema subset, tools, Ollama, testing
├── http/                           500   adapter, middleware, routing, requests, testing
├── database/                       572   provider, contracts, migrations, testing (the conformance suite)
├── plugins/                        414   protocol, config, registry
└── cli/                            816   check, new, run, migrate, targets, scaffold

tests/                           14 430 lines, 991 tests
examples/                        11 648 lines, sixteen worked examples
site/                             9 463 lines of scripts and pages, minus the generated reference
docs/                             a guide per subsystem, plus cross-cutting pages and 17 ADRs
```

The three directory totals are counted by the command in section 12 — every line in the directory,
blank ones included, and the generated pages excluded — so they can be re-measured rather than trusted.
The `src/xyberos` breakdown above is the one the map was drafted with. The map is for orientation, not
for arithmetic: what matters is that more than half the source is durable execution and AI, while the
surface a newcomer meets first is the smallest part of it.

## 12. Verify it yourself

Everything claimed above is checkable in a few minutes:

```powershell
python -m pip install -e ".[dev,http,database]"
python -m pytest                                  # 991 tests, 7 skip without live Ollama
python -m pytest -s tests/perf                    # the resource baselines
python -m pytest -q --collect-only tests/runtime # 77 tests for the runtime alone
ruff check src tests examples site/scripts; mypy  # lint and strict types, 193 sources
python site/scripts/build.py --check              # the documentation site builds strictly
python -m build                                   # wheel + sdist, then
python -m venv .smoke; .smoke\Scripts\pip install dist\*.whl
```

The line counts in section 11 come from one command, so they can be re-measured rather than trusted:

```powershell
python -c "import pathlib; [print(d, sum(len(p.read_text('utf-8', errors='ignore').splitlines()) for p in pathlib.Path(d).rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'reference' not in p.parts and p.name != 'roadmap.md')) for d in ('tests', 'examples', 'site')]"
.smoke\Scripts\xyberos check                      # the CLI from an installed artefact
```

Start with the [getting started guide](getting-started.md) if you want to hold the code before reading
it, or the [tutorial](tutorial.md) if you want to be walked through it.
