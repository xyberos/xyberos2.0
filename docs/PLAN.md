# Xyberos — architecture baseline and roadmap

Python · Starlette · SQLite · Composable runtime · Explicit typed dependencies · Explicit Workflow · Experimental durability

This document is the stable architecture baseline: decisions, subsystem contracts, target
structure, roadmap, and risk analysis. It is not the task tracker.

| Document | Owns |
| --- | --- |
| `PLAN.md` (this file) | Architecture baseline, subsystem contracts, roadmap rationale, risks, definition of done |
| [`implementation.md`](./implementation.md) | Authoritative phase-by-phase work packages, exit gates, status, and cross-phase controls |
| [`runtime.md`](./runtime.md) | The implemented Phase 1 public runtime surface |
| [`adr/`](./adr/) | Immutable decisions that affect public behavior |

## 1. Final architecture decisions

The following decisions are now the foundation of the Xyberos implementation plan.

HTTP foundation: Starlette

Use Starlette for ASGI routing, middleware, request/response handling, and lifespan integration. Xyberos supplies the developer-facing application API above it.

Runtime: Composable Runtime + Capability Registry

Build a small application runtime with explicit service registration, dependency resolution, configuration, lifecycle, and plugin contracts. Do not introduce a large centralized kernel.

Dependency injection: Explicit typed dependencies

Use explicit dependency declarations and type annotations. Avoid hidden global service locators and fragile parameter-name-based injection.

Database: SQLite by default

Provide a zero-configuration SQLite setup and a database-provider contract. Reuse existing database libraries rather than building a custom ORM.

Execution: Direct execution + Workflow

Support ordinary function calls first, then explicit multi-step Workflow for branching, retries, timeouts, and cancellation.

Durability: Native SQLite MVP, experimental

Design the execution-store interface and prototype a single-instance durable executor. Do not make crash recovery a stable platform guarantee in the initial release.

### Initial release scope

Stable target: Runtime + capability registry + Starlette integration + SQLite provider + plugins + explicit Workflow.

Experimental target: Native SQLite durable execution.

This distinction is important: the initial stable release must be useful even if the durable execution subsystem is disabled entirely.

## 2. Architecture overview

Developer API

App · Routes · Typed dependencies · Services · AI facade

Composable Runtime

Lifecycle · Configuration · Dependency resolution · Error handling

Capability Registry

Database · Auth · Storage · Cache · AI providers · Plugins

Execution Layer

Direct calls · Workflow · Experimental durable execution

HTTP adapter

Starlette · ASGI · Middleware

Persistence adapters

SQLite · Execution journal · Provider interfaces

The registry and execution layer are separate. The registry describes available capabilities; the execution layer determines how work runs. HTTP middleware is confined to HTTP concerns, and the durable executor does not become a mandatory path for ordinary application requests.

## 3. Core architectural contracts

Before implementing features, establish the contracts between subsystems. These contracts will determine whether Xyberos remains composable as it grows.

### 3.1 Application runtime

The runtime owns:

- Application configuration and environment settings.
- Component registration and dependency resolution.
- Startup, readiness, shutdown, and resource cleanup.
- Plugin initialization and validation.
- Logging integration and execution context.
- Application-wide error handling.

The runtime does not own database query logic, AI reasoning, HTTP middleware execution, or workflow history.

### 3.2 Capability registry

Each capability has a name, contract, provider, configuration, and lifecycle.

Example:

| Capability  | Contract                    | Initial provider    |
| ----------- | --------------------------- | ------------------- |
| `database`  | Database provider           | SQLite              |
| `http`      | HTTP adapter                | Starlette           |
| `cache`     | Cache interface             | In-memory           |
| `storage`   | Storage interface           | Local filesystem    |
| `ai`        | Model provider interface    | Optional provider   |
| `knowledge` | Retrieval interface         | Optional subsystem  |
| `execution` | Execution interface         | In-process          |
| `durable`   | Durable execution interface | Experimental SQLite |

Registry rules:

1. Register capabilities before serving requests.
2. Validate required dependencies during startup.
3. Reject duplicate registrations by default.
4. Support explicit provider replacement for testing and configuration.
5. Define ownership and cleanup for every managed resource.
6. Avoid a mutable global registry shared across unrelated application instances.

Use application-scoped dependencies for shared services, request-scoped dependencies for request-specific state, and transient dependencies only when a new instance is actually required.

### 3.3 Explicit typed dependency injection

Use a documented dependency marker or provider declaration. Do not infer dependencies merely from parameter names.

A proposed API:

```python
from typing import Annotated

from xyberos import App, Inject, Scope, Settings


class UserService:
    async def list_users(self) -> list[str]:
        return []


app = App(settings=Settings.load())
app.provide(UserService, factory=UserService, scope=Scope.APP)
```

Phase 2 reuses the same marker for handler injection:

```python
@app.get("/users")
async def list_users(users: Annotated[UserService, Inject()]) -> list[str]:
    return await users.list_users()
```

The runtime should resolve the `UserService` annotation, construct or retrieve the appropriate instance, and fail at startup if a required dependency cannot be resolved.

The exact syntax may change during implementation, but the following behavior should not:

- Dependencies are declared explicitly.
- Type hints are checked.
- Dependency cycles produce actionable errors.
- Scope violations are rejected.
- Tests can override dependencies.
- Cleanup occurs in reverse dependency order.

### 3.4 Plugin contract

A plugin contributes capabilities and optionally routes, configuration, and lifecycle hooks.

```python
class DatabasePlugin:
    name = "database"

    def register(self, registry, config):
        registry.provide(
            DatabaseProvider,
            create_sqlite_provider(config.database),
            scope="app",
        )
```

This is illustrative pseudocode. The implementation should formalize the plugin interface and decide how configuration schemas, dependency declarations, and async lifecycle hooks are represented.

Keep plugins in-process for the first release. Treat third-party plugins as trusted code unless a separate isolation mechanism is implemented.

### 3.5 Provider interfaces

Use Python `Protocol` or abstract base classes for the boundaries that genuinely need substitution.

For example:

```python
from typing import Any, Protocol


class ExecutionStore(Protocol):
    async def create_execution(
        self, execution_id: str, definition: str, input: Any
    ) -> None: ...

    async def get_execution(self, execution_id: str) -> Any: ...

    async def save_step_result(
        self, execution_id: str, step_id: str, result: Any
    ) -> None: ...
```

The durable store will need additional operations for atomic state transitions, claims, retries, cancellation, and recovery. The initial contract should be finalized from those requirements rather than implemented as a generic key-value store.

## 4. Subsystem implementation plan

### 4.1 Runtime and application API

Build the runtime as the smallest usable unit.

Implementation tasks

- Create the `App` object.
- Add configuration loading and validation.
- Implement application and request contexts.
- Add typed dependency registration and resolution.
- Define startup and shutdown ordering.
- Add structured exceptions and logging integration.
- Validate registrations before the server accepts traffic.

Acceptance criteria

- A minimal app can start and shut down cleanly.
- Startup failure identifies the component and dependency involved.
- Resources are released even when another shutdown hook fails.
- Two app instances can run independently in the same process.
- The runtime does not require importing AI or durable execution packages.

### 4.2 Starlette integration

Starlette remains the HTTP engine. Xyberos should wrap it, not fork or reimplement it.

Implementation tasks

- Route registration through the Xyberos application API.
- Request and response handling.
- Typed dependency injection into handlers.
- Middleware configuration and ordering.
- Exception handling and validation integration.
- Lifespan coordination with the runtime.
- A test client and route-testing utilities.
- OpenAPI support through an appropriate integration.

Acceptance criteria

- Middleware behaves according to a documented ordering model.
- Runtime startup completes before requests are accepted.
- Shutdown waits for managed resources to close within configured limits.
- HTTP concerns do not leak into database, Workflow, or durable execution abstractions.

### 4.3 SQLite and database providers

SQLite should require no separate server setup for the initial application experience.

Implementation tasks

- Define the database provider interface.
- Integrate a mature SQLite driver and database-access library.
- Support configuration, connections, transactions, and cleanup.
- Integrate migrations instead of building a migration engine.
- Add test fixtures and temporary database support.
- Document concurrency limitations and deployment assumptions.

Acceptance criteria

- A fresh app can initialize its database with minimal configuration.
- Transaction failures roll back correctly.
- Connections and transactions have well-defined ownership.
- Tests cover concurrent requests and SQLite write contention.
- A future provider can be introduced without rewriting business services.

### 4.4 Workflow engine

Workflow is the explicit execution layer for multi-step work. It should not be required for ordinary functions or HTTP handlers.

Initial features

- Named steps with declared inputs and outputs.
- Sequential execution.
- Conditional branches.
- Bounded retries and backoff.
- Step and overall timeouts.
- Cancellation.
- Error propagation and handling policies.
- Execution metadata and tracing.

Defer initially

- Arbitrary distributed DAG scheduling.
- Automatic multi-agent planning.
- Unbounded loops.
- Implicit agent-generated control flow.
- Distributed task queues.
- Full replay and crash-recovery guarantees.

Acceptance criteria

- A workflow can be inspected and tested without a live model provider.
- Step failures produce structured execution errors.
- Retry counts and timeouts are deterministic and testable.
- Cancellation propagates to supported operations.
- No documentation implies persistence or recovery for ordinary in-process Workflow.

**Shipped in Phase 4.** All five criteria are now verified against the implementation: `Workflow`
lives in `src/xyberos/execution/` with no optional dependency, the exit-gate suite in
`tests/workflow/` covers every criterion deterministically with a virtual clock, and
`docs/workflow.md` states the absence of persistence where a reader would look for it. The frozen
contract is [ADR 0009](./adr/0009-workflow-engine-contract.md), and the naming decision is
[ADR 0008](./adr/0008-workflow-terminology.md).

### 4.5 AI facade

The AI facade should use the same capability and dependency model as other services.

Initial interfaces:

- Chat or text generation.
- Structured outputs.
- Model and provider configuration.
- Tool registration and invocation.
- Embeddings.
- Knowledge retrieval integration.
- Timeouts, token usage, and error reporting.

Model providers should be optional adapters. Keep provider-specific request formats outside the runtime core.

AI calls should use direct execution by default. A developer should opt into Workflow for explicit multi-step orchestration and into durable execution only when the task needs persisted progress and recovery.

**Shipped in Phase 5.** The facade, provider-neutral contracts, tool contract, closed schema subset,
and fake provider are dependency-free and live in `src/xyberos/ai/`, so "no AI SDK installed" is a
supported configuration rather than a degraded one; the Ollama adapter is the only module behind the
`ollama` extra. Chat, structured output, streaming, embeddings, and tool invocation all shipped, and
`examples/ai_assistant` runs them through the same DI, plugin, and Workflow contracts as any other
service. The frozen contract is [ADR 0010](./adr/0010-ai-facade-contract.md) and the guide is
[`docs/ai.md`](./ai.md).

Two interfaces in the list above did **not** ship, and the phase plan is why:

- **Knowledge retrieval integration** is deferred until it has its own storage, chunking, filtering,
  authorization, and evaluation contracts. Embeddings and the tool allowlist are the interface a
  retrieval layer would build on; the layer itself would be a guess today.
- **Provider capability discovery** is *declared*, not probed, with one exception: the Ollama
  adapter cross-checks a declared `tools` claim against what a model reports through `/api/show`,
  because that is the only capability the API exposes. The rest stay the operator's claim, which
  keeps a wrong claim a configuration bug instead of a silent false promise.

### 4.6 Experimental native SQLite durability

Implement this after the runtime and Workflow APIs are stable.

The initial durable executor should support:

- Persistent execution IDs.
- A defined state machine.
- Atomic execution and step-state updates.
- A persisted execution journal.
- Worker claims and leases.
- Bounded retries and retry scheduling.
- Cancellation requests.
- Recovery after process restart.
- Execution inspection.
- Versioned workflow definitions.

Use a separate execution-store interface. Do not put workflow history into the application database provider's general-purpose API.

Initial limitation: single-instance execution only. Do not claim safe multi-host execution or Temporal-equivalent guarantees.

## 5. Native durable execution: detailed design

This subsystem is the highest-risk part of the architecture. Its design should be narrow enough to implement, but its persistence semantics must be correct.

### 5.1 Execution lifecycle

Non-terminal states:

- `PENDING` — the execution is accepted and persisted but not yet owned.
- `RUNNING` — a worker owns an active lease.
- `RETRYING` — a failed attempt is being rescheduled.
- `WAITING` — the execution is parked on a scheduled retry or an external signal.

Terminal states: `COMPLETED`, `FAILED`, `CANCELLED`, and `TIMED_OUT`. Legal transitions must be validated and persisted atomically.

A production implementation needs a formal transition table, including how cancellation interacts with a running step and how expired leases are recovered.

### 5.2 Initial persistence schema

Use SQLite tables with transactional updates. A starting schema can contain:

| Table                  | Purpose                                                       |
| ---------------------- | ------------------------------------------------------------- |
| `workflow_definitions` | Workflow name, version, and definition metadata               |
| `executions`           | Execution ID, input, status, timestamps, and workflow version |
| `execution_steps`      | Step ID, status, attempts, result reference, and timestamps   |
| `execution_events`     | Ordered execution state transitions and diagnostic metadata   |
| `worker_leases`        | Ownership, lease expiry, and fencing information              |
| `scheduled_retries`    | Retry eligibility and next-run time                           |

Keep the execution store distinct from application business tables. Store large step outputs separately when necessary, and avoid storing credentials or unrestricted sensitive payloads in execution history.

SQLite transactions should protect related state changes. A worker should claim work atomically, and expired leases should only permit recovery after the previous owner is no longer authorized to commit state.

### 5.3 Recovery rules

The durable executor must define what happens at each failure boundary.

| Failure                           | Required behavior                                           |
| --------------------------------- | ----------------------------------------------------------- |
| Crash before a step starts        | Recover and schedule the step                               |
| Crash after a result is persisted | Reuse the recorded result                                   |
| Crash during an activity          | Retry or reconcile according to its policy                  |
| Lost external API response        | Use idempotency or reconciliation; outcome may be uncertain |
| Expired worker lease              | Recover only after validating lease ownership and fencing   |
| Invalid workflow version          | Stop safely and report a compatibility error                |
| Cancellation during execution     | Record cancellation and stop supported work safely          |

Important: a persisted step result is not proof that an external side effect happened exactly once. If an email, payment, or API call succeeds and the process crashes before saving the result, the executor needs idempotency support or a reconciliation strategy.

### 5.4 Why durability remains experimental

A single SQLite database can be sufficient for an early local execution engine, but durability includes more than writing rows.

Before promotion to stable status, demonstrate:

- Atomic claims and state transitions.
- Safe restart recovery.
- Idempotent result persistence.
- Lease expiration and ownership fencing.
- Workflow definition compatibility.
- Retry and cancellation correctness.
- Bounded resource consumption.
- Reliable database backup and recovery procedures.

Do not add distributed scheduling or multi-host guarantees until the single-instance model is reliable.

## 6. Target repository structure

Use a modular monolith, with optional subsystems separated by import and dependency boundaries.

The tree below is the **target** layout. It is not a description of the current tree, and it is
not a requirement to create empty modules: implement a module only when its responsibilities and
contracts are understood. Phases 1–5 currently implement:

```text
src/xyberos/
├── __init__.py          # public re-exports
├── _extras.py           # missing-extra guidance for optional imports
├── app.py               # App, RequestContext, lifecycle, plugins
├── config.py            # typed settings, including plugin and ai sections
├── diagnostics.py       # provider and plugin diagnostics
├── errors.py            # error taxonomy, including the workflow and AI families
├── routing.py           # dependency-free route records
├── runtime/
│   ├── __init__.py
│   ├── context.py       # contextvars and logging helpers
│   ├── dependencies.py  # registry, records, graph validation
│   └── lifecycle.py     # LifecycleState
├── plugins/             # trusted plugin contract, configuration, and registry
│   ├── protocol.py, config.py, registry.py
├── execution/           # in-process workflow engine (core, no extra)
│   ├── models.py        # immutable Workflow, Step, Edge, results
│   ├── policies.py      # retry, backoff, clock, cancellation, step context
│   ├── validation.py    # build-time graph validation
│   ├── executor.py      # structured-concurrency execution
│   ├── events.py        # structured execution events
│   ├── direct.py        # the single-call execution boundary
│   └── testing.py       # ManualClock, FakeExternalService, Reply
├── ai/                  # provider-neutral facade (core, no dependency)
│   ├── contracts.py     # requests, responses, usage, capabilities, protocols
│   ├── schema.py        # closed JSON Schema subset
│   ├── tools.py         # allowlisted tool contract and audit events
│   ├── facade.py        # AIFacade and the logging policy
│   ├── testing.py       # FakeModelProvider and scripted replies
│   └── ollama.py        # the Ollama adapter; only module behind the "ollama" extra
├── http/                # optional "http" extra (Starlette)
│   ├── adapter.py, middleware.py, routing.py, requests.py, testing.py
└── database/            # optional "database" extra (SQLAlchemy Core, aiosqlite, Alembic)
    ├── contracts.py, migrations.py, sqlite.py, testing.py

examples/
├── sqlite_crud/         # worked CRUD slice with Alembic migrations
├── custom_plugin/       # plugin authoring example
├── workflow/            # workflow example with retries, branching, and events
└── ai_assistant/        # AI facade wired through a plugin, DI, routes, and a workflow

tests/
├── runtime/             # Phase 1 exit-criteria tests
├── http/                # adapter and handler-compilation tests
├── database/            # provider, PRAGMA, and contention tests
├── plugins/             # plugin contract, configuration, and lifecycle tests
├── workflow/            # Phase 4 exit-criteria tests
├── ai/                  # Phase 5 exit-criteria tests, including the Ollama adapter
├── integration/         # end-to-end example, migration, plugin-package, workflow, and AI tests
├── fixtures/            # separately packaged plugin used as a test fixture
├── contracts/           # executable public-API examples
├── test_import_boundary.py
└── test_public_api.py
```

The target layout is:

```

xyberos3/
├── pyproject.toml
├── README.md
├── docs/
│   ├── PLAN.md              # architecture baseline (this file)
│   ├── implementation.md    # phase plan and status
│   ├── runtime.md           # implemented runtime surface
│   ├── http.md              # HTTP adapter guide
│   ├── database.md          # database provider guide
│   ├── plugins.md           # plugin guide
│   ├── workflow.md          # workflow engine guide
│   └── adr/                 # decision records
├── examples/
│   ├── hello_app/
│   ├── sqlite_crud/
│   ├── custom_plugin/
│   ├── workflow/
│   ├── ai_assistant/
│   └── durable_workflow/
├── src/
│   └── xyberos/
│       ├── __init__.py
│       ├── app.py
│       ├── config.py
│       ├── errors.py
│       ├── runtime/
│       │   ├── lifecycle.py
│       │   ├── context.py
│       │   └── dependencies.py
│       ├── plugins/
│       │   ├── base.py
│       │   └── loader.py
│       ├── http/
│       │   ├── adapter.py
│       │   ├── routing.py
│       │   └── middleware.py
│       ├── database/
│       │   ├── contracts.py
│       │   └── sqlite.py
│       ├── execution/
│       │   ├── direct.py
│       │   ├── events.py
│       │   ├── executor.py
│       │   ├── models.py
│       │   ├── policies.py
│       │   ├── testing.py
│       │   └── validation.py
│       ├── ai/
│       │   ├── facade.py
│       │   ├── providers.py
│       │   └── tools.py
│       ├── durable/
│       │   ├── contracts.py
│       │   ├── models.py
│       │   ├── store.py
│       │   ├── journal.py
│       │   ├── scheduler.py
│       │   ├── worker.py
│       │   └── recovery.py
│       └── cli/
└── tests/
    ├── test_import_boundary.py   # implemented
    ├── test_public_api.py        # implemented
    ├── test_package.py           # implemented
    ├── runtime/          # implemented (Phase 1)
    ├── http/             # implemented (Phase 2)
    ├── database/         # implemented (Phase 2)
    ├── plugins/          # implemented (Phase 3)
    ├── workflow/         # implemented (Phase 4)
    ├── ai/               # implemented (Phase 5)
    ├── fixtures/         # implemented (separately packaged plugin)
    ├── contracts/        # implemented (executable API examples)
    ├── integration/      # implemented
    ├── durable/          # planned
    └── crash_recovery/   # planned

```

The directory layout is a target, not a requirement to create empty modules upfront. Implement a module only when its responsibilities and contracts are understood. A target module may be split once its real responsibilities are clear, as `execution/` was: `models`, `policies`, `validation`, `executor`, `events`, `direct`, and `testing` are separate because they are separately testable, not because the plan predicted those exact names.

Keep `durable/` importable independently of the core. An installation that does not use experimental durability should not need its dependencies or initialize its database tables.

## 7. Development roadmap

The roadmap prioritizes a usable stable runtime before experimental durability. Work packages,
exit gates, and current status live in [`implementation.md`](./implementation.md); this section
is the summary.

| Phase | Scope | Deliverable | Estimate | Status |
| --- | --- | --- | --- | --- |
| 0 | Architecture and API specification | ADRs and executable API-contract examples | 3–5 days | complete |
| 1 | Runtime foundation | A working minimal application | 1–2 weeks | complete |
| 2 | HTTP and traditional application support | A working CRUD application | 1–2 weeks | complete |
| 3 | Plugins and capabilities | An independently developed plugin | 1–2 weeks | complete |
| 4 | Stable in-process Workflow | A tested, inspectable workflow engine without durability promises | 2–3 weeks | complete |
| 5 | AI facade and integration | An AI application built on the same runtime and Workflow APIs | 1–2 weeks | complete |
| 6 | Experimental durable execution | An experimental single-instance executor with documented limits | 3–6+ weeks | next |
| 7 | DX, hardening, and release | A stable runtime and Workflow release; durability remains experimental | 1–2 weeks | planned |

Estimated initial implementation: approximately 10–18+ working weeks for one experienced developer, including a limited experimental durable executor. The work can take longer if building and validating recovery semantics reveals additional requirements.

The stable runtime and Workflow can be released earlier; there is no reason to block the useful framework on durable execution.

## 8. Testing and quality gates

Testing should be built into each phase, not postponed until the end.

| Area                 | Required tests                                                       |
| -------------------- | -------------------------------------------------------------------- |
| Runtime              | Lifecycle ordering, configuration validation, isolated app instances |
| Dependency injection | Missing providers, cycles, scope validation, overrides               |
| Plugins              | Dependency order, duplicate registration, startup failure, cleanup   |
| HTTP                 | Routing, middleware order, exception handling, async behavior        |
| SQLite               | Transactions, migrations, connection cleanup, concurrent writes      |
| Workflow                 | Branches, retry limits, timeouts, cancellation, error propagation    |
| AI                   | Provider failures, malformed outputs, tool permissions, usage limits |
| Durability           | Crash recovery, duplicate work, lease expiry, interrupted steps      |
| Packaging            | Clean installation, optional dependencies, supported Python versions |

### Required release gates

Stable runtime gate

A developer can build, test, and run a SQLite-backed HTTP application without importing AI or durability modules.

Stable Workflow gate

Execution order, branching, retries, cancellation, and errors have documented semantics and automated tests.

Experimental durability gate

Automated process-kill and restart tests validate the documented recovery behavior. Unsupported guarantees are explicitly excluded.

Use CI to run unit tests, integration tests, type checking, linting, package builds, and dependency-compatibility checks. Add deterministic fault-injection tests for the durable executor.

## 9. Developer experience requirements

Xyberos should feel like a normal Python framework rather than an infrastructure platform.

Prioritize these deliverables:

- A minimal application template.
- A SQLite CRUD example.
- A plugin-development example.
- An AI assistant example.
- A Workflow example with branching and retries.
- A separate experimental durable-workflow example.
- Clear errors when configuration or dependencies are invalid.
- A test client and easy dependency overrides.
- Documentation that distinguishes direct, in-process, and durable execution.

The command-line interface can initially be limited to project creation, development server startup, and configuration or diagnostics commands. Do not build a large CLI before the underlying APIs are stable.

## 10. Risks and mitigations

| Risk                                           | Mitigation                                                                              |
| ---------------------------------------------- | --------------------------------------------------------------------------------------- |
| Runtime becomes a new kernel                   | Keep core responsibilities limited to lifecycle, composition, and dependency resolution |
| Registry becomes a global service locator      | Use explicit typed injection and scoped dependencies                                    |
| Workflow grows into a universal workflow framework | Limit stable Workflow to a well-defined set of execution primitives                         |
| SQLite executor makes unsafe recovery claims   | Keep it experimental and single-instance until failure semantics are validated          |
| Plugin API becomes unstable                    | Finalize lifecycle and registration contracts before broad plugin development           |
| Too many abstractions slow development         | Reuse existing Python libraries and introduce interfaces where substitution is valuable |
| AI functionality dominates the core            | Keep AI providers and knowledge integrations optional                                   |
| Async code blocks the server                   | Define policies for blocking I/O, CPU-intensive work, and worker execution              |

## 11. Definition of done for Xyberos

The first stable release is ready when a developer can:

1. Create a project with a single application object.
2. Expose HTTP routes using Starlette underneath.
3. Use SQLite without configuring an external database server.
4. Inject services using explicit typed dependencies.
5. Add and replace capabilities through plugins.
6. Build ordinary applications without loading AI or Workflow.
7. Build explicit, testable multi-step workflows.
8. Add an AI provider and tools without changing the runtime architecture.
9. Test applications without requiring live infrastructure wherever practical.
10. Understand exactly which execution modes offer persistence and recovery.

Durable execution remains experimental until its persistence, recovery, and side-effect guarantees are independently demonstrated.

## Final architecture decision record

Foundation

Composable runtime + capability registry + explicit typed dependencies.

Application infrastructure

Starlette + SQLite default + modular plugin contracts.

Execution

Direct execution by default, explicit in-process Workflow for multi-step work, and optional experimental native SQLite durability.

Release priority

Ship a useful, developer-friendly runtime and Workflow first. Do not delay the stable platform to achieve production-grade durability in version 3.0.

The central architectural rule for Xyberos is:

Compose the application through the runtime, expose functionality through capabilities, define multi-step behavior through Workflow, and add durable execution only when recovery is required.

This provides a manageable implementation path while keeping the framework extensible enough for conventional applications, AI systems, and future reliable workflow execution.

## Appendix A — Reviewed recommendations and disposition

An external review proposed five changes to this baseline. Each proposal was evaluated against
the project constraints (thin runtime, no optional imports in core, validated failure semantics)
and folded into the plan as follows. Accepted items are already reflected in sections 4 and 5
and in [`implementation.md`](./implementation.md).

| # | Recommendation | Disposition | Where it landed |
| --- | --- | --- | --- |
| 1 | Force WAL mode and a bounded busy timeout; keep the durable journal in a separate SQLite file | Accepted | Phase 2 work packages 5–6 and the durable requirements in section 5 |
| 2 | Bake `contextvars` into the runtime and copy context across step, task, and thread boundaries | Accepted | `src/xyberos/runtime/context.py` (Phase 1); Phase 4 propagates it across steps |
| 3 | Validate the dependency graph at startup instead of per request | Accepted | Phase 1 validates before readiness; see [ADR 0005](./adr/0005-phase-1-runtime-contract.md) |
| 4 | Add a decorator or imperative Workflow API alongside the declarative builder | Deferred | Deferred until declarative Workflow introspection and recovery semantics are proven; see the backlog in [`implementation.md`](./implementation.md) |
| 5 | Move the AI facade ahead of the stable Workflow engine | Rejected | Workflow semantics stabilize first; Phase 4 uses a deterministic fake provider, so no reordering is needed |

Rationale for the two proposals that were not accepted:

- **Decorator Workflow (deferred).** An imperative `async def workflow(ctx)` body is arbitrary Python
  control flow. It cannot be reliably inspected, retried, or recovered, so it cannot carry the
  stable Workflow contract. A decorator surface can be added later as sugar over the declarative
  graph, once the graph semantics are frozen.
- **AI facade before Workflow (rejected).** AI adapters are the largest source of optional
  dependencies and provider churn. Gating core Workflow work on an adapter would invert the
  dependency direction and slow the stable release. Phase 4 instead exercises retries,
  deadlines, and cancellation against a deterministic in-process fake that needs no network or
  model provider.

Housekeeping in this revision: the collapsed code blocks in sections 3.3–3.5 were repaired, the
scrambled execution-state list in section 5.1 was rewritten, the repository tree in section 6 now
distinguishes the implemented Phase 1 layout from the target layout, and the pasted review text
that previously ended this file was replaced by this appendix. The file is UTF-8 without a BOM.
