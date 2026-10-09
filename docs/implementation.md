# Xyberos 2.0 Implementation Plan

## Objective

Turn the architecture described in [docs/xyberos2.0.md](./docs/xyberos2.0.md) into a staged, working implementation that keeps the kernel small, secure, and extensible while validating the first practical application vertical slice.

This plan incorporates the architectural decisions in the document and adds targeted improvements for runtime safety, provider defaults, and operational visibility.

## 1. Architectural direction

### 1.1 Core principle

Xyberos 2.0 should ship in working vertical slices rather than by building a large abstraction layer first.

The first release should prove:

- the kernel starts and shuts down cleanly
- configuration is validated
- subsystems can be registered and initialized
- execution context is request-scoped and safe
- a database subsystem can run against SQLite
- a basic web application can serve requests with security-aware context propagation

Only after that baseline is stable should the project expand into AI, P2P, knowledge, or advanced workflow features.

### 1.2 Recommended implementation order

Priority levels match the document:

- P0: kernel foundation, SQLite provider, traditional app slice, flow engine
- P1: provider ecosystem and AI subsystem
- P2: P2P and production hardening

## 2. Implementation milestones

### Phase 1 — Kernel foundation (P0)

#### Deliverables

- `xyberos.kernel.contracts`
- `xyberos.kernel.runtime`
- `xyberos.kernel.config`
- `xyberos.kernel.registry`
- `xyberos.kernel.context`
- `xyberos.kernel.lifecycle`

#### Scope

- Define the base contracts for:
  - `Subsystem`
  - `Provider`
  - `ProviderRegistry`
  - `ExecutionContext`
  - `Capability`
  - `PolicyEngine`
  - `EventBus`

- Implement the minimal runtime:
  - startup lifecycle
  - shutdown lifecycle
  - dependency container
  - subsystem registry
  - provider registry
  - config validation

- Ensure context is propagated safely across async boundaries.

Define the `FlowEngine` contract alongside the flow step model in Phase 3, so the contract reflects a real execution model rather than being an unused placeholder in the kernel.

#### Exit criteria

- app boots with a valid configuration
- missing subsystem registrations fail with explicit errors
- if startup fails partway through, already-started subsystems are shut down in reverse order
- shutdown cleans up successfully initialized resources without leaking state and is safe to call repeatedly
- no subsystem can initialize after kernel boot without an explicit reconfiguration path

### Phase 2 — Traditional application vertical slice (P0)

#### Deliverables

- `xyberos.http` Starlette adapter
- `xyberos.subsystems.database` contract
- `xyberos.providers.database.sqlite` provider
- trusted identity handoff from the HTTP authentication layer into execution context
- sample CRUD application

#### Scope

- Add HTTP middleware for request-scoped execution context; require identity from an injected, trusted authentication resolver
- Treat tenant and actor headers as untrusted input; establish identity through authentication
- Add SQLite provider with WAL for file-backed databases where appropriate
- Add connection lifecycle, transaction handling, and busy-timeout behavior
- Create one working CRUD application with tenant-scoped data access
- Add HTTP/database integration tests for unauthenticated requests and cross-tenant access

#### Exit criteria

- application starts with SQLite alone
- request metadata is captured correctly, while trusted identity comes from authentication
- requests operate under isolated execution context
- forged tenant/actor headers cannot bypass authorization or tenant isolation
- unauthenticated requests to protected routes are rejected
- database writes and reads use parameterized SQL and enforce tenant scope
- the app runs without external database services or AI dependencies

### Phase 3 — Hybrid Flow engine (P0)

#### Deliverables

- flow step contracts
- flow executor
- retries, cancellation, and timeout support
- execution traces and structured errors

#### Scope

- Define typed step inputs and outputs
- Support sequential and conditional execution
- Support explicit execution policies for async, thread, and process workloads
- Define retry eligibility and idempotency behavior before enabling automatic retries
- Add step-level tracing and observability
- Keep AI optional and non-authoritative for security decisions

#### Exit criteria

- flow can execute deterministically without model dependencies
- timeouts and cancellation are enforced
- failed flow steps produce structured diagnostics
- retries cannot silently duplicate non-idempotent side effects
- authorization and capability checks happen outside the flow runtime

The initial engine is sequential and in-process, with a configurable bound on concurrent flow runs. Dependencies can be explicitly injected into the engine and read from each step's `FlowState`. Async steps must use async handlers; synchronous lightweight steps run inline; thread steps run through `asyncio.to_thread`; process steps require an application-owned executor that is injected into the engine. The caller owns and shuts down that executor, and values passed to process steps must be pickleable. Step traces are returned in results/errors and can be forwarded to an optional sync or async observer; observer failures are surfaced explicitly. Timeouts include queue wait and cancel the awaiting flow, but Python cannot forcibly stop already-running synchronous work in a thread or process; use cooperative cancellation or a managed worker/service when hard termination is required. Automatic retries are opt-in, require an idempotent step and explicit retryable exception types, and do not retry timeouts or cancellation.

`FlowSubsystem` registers the configured engine through the `FlowEngineContract` in the kernel dependency container and unregisters it on shutdown. The process executor remains application-owned and is not shut down by the subsystem.

### Phase 4 — Provider ecosystem (P1)

#### Deliverables

- PostgreSQL provider using the optional `psycopg` extra
- blob provider contract and local filesystem implementation
- lifecycle subsystems that expose configured database and blob providers
- config compatibility checks
- provider tests

#### Scope

- Register trusted provider instances explicitly in application code; select among
  those instances through subsystem configuration. Provider names must match their
  registry keys, and provider instances must implement the subsystem contract.
- Configure the database subsystem with a selected provider and its provider-owned
  settings:

  ```python
  DatabaseSubsystem(
      {
          "sqlite": SQLiteProvider(),
          "postgresql": PostgreSQLProvider(),
      }
  )
  ```

  ```yaml
  database:
    provider: postgresql
    config:
      conninfo: "<injected securely from XYBEROS_DATABASE_URL>"
      connect_timeout: 10
  ```

- Keep PostgreSQL support optional so the core and SQLite-only installations do not
  require a PostgreSQL driver. Install the `postgres` extra to use it. PostgreSQL
  configuration requires non-empty `conninfo`; credentials should come from
  environment or a secrets provider, never committed configuration.
- Use the common database contract for portable SQL. The PostgreSQL adapter accepts
  qmark placeholders (`?`) for positional parameters and `:name` placeholders for
  mappings, while preserving placeholder-like text in quoted strings and comments.
  PostgreSQL-specific operators that use `?` can be ambiguous with this portable
  placeholder convention; use an equivalent function such as `jsonb_exists` in
  portable application queries.
- Define blob content and metadata operations independently of the storage backend.
  The initial local provider stores generated, traversal-safe identifiers in
  per-blob directories, writes content and metadata through a staging directory,
  and supports an optional maximum blob size:

  ```python
  BlobSubsystem(LocalFilesystemBlobProvider())
  ```

  ```yaml
  blob:
    provider: local_filesystem
    config:
      root: ./data/blobs
      max_size_bytes: 10485760
  ```

- Treat local filesystem storage as a single-host development or deployment option,
  not shared or highly available object storage. Applications needing those
  properties should add a compatible remote blob provider.
- Verify behavior with provider contract tests, configuration rejection tests, and
  optional integration tests against real PostgreSQL. The PostgreSQL integration
  test runs only when `psycopg` is installed and `XYBEROS_TEST_POSTGRES_DSN` points
  to a dedicated test database.

#### Exit criteria

- registered providers can be selected by configuration without rewriting app
  logic; unregistered or incompatible providers fail with actionable errors
- SQLite and local blob contract tests verify data, lifecycle, and validation
  behavior
- PostgreSQL placeholder/configuration behavior is tested, and live database
  integration is explicitly opt-in
- no PostgreSQL driver is required for the SQLite-only installation

### Phase 5 — AI subsystem (P1)

#### Deliverables

- provider-neutral model contract and OpenAI-compatible HTTP adapter
- validated intent proposal service
- tenant/actor/conversation-scoped memory contract and bounded in-memory provider
- optional tenant- and actor-filtered knowledge contract and keyword provider

#### Scope

- Keep AI optional: install and initialize `AISubsystem` only in applications that
  require model requests. The initial `OpenAICompatibleProvider` uses Python's
  standard library and supports hosted and local OpenAI Chat Completions-compatible
  endpoints. Supply API credentials through secure configuration; non-loopback
  endpoints must use HTTPS, while plain HTTP is allowed only for loopback. Register
  the application's `PolicyEngine`
  in the kernel dependency container before startup. `AISubsystem` exposes a guarded
  model-provider facade that requires trusted execution context and approval for
  the `ai.generate` capability; inject this facade, not the raw provider, into flows.
  By default it targets Ollama's local OpenAI-compatible endpoint at
  `http://localhost:11434/v1` and selects `llama3.2`. Ollama must be running and the
  model must be available locally; model requests fail explicitly if either is
  unavailable. Set `base_url` and `model` to use another Ollama model or compatible
  service. For the default, install/start Ollama and pull it with `ollama pull
  llama3.2`.

  ```python
  AISubsystem(OpenAICompatibleProvider())
  ```

  ```yaml
  ai:
    provider: openai_compatible
    config:
      base_url: http://localhost:11434/v1
      model: llama3.2
      timeout_seconds: 30
      max_input_chars: 100000
      max_output_tokens: 2048
  ```

- Ollama commonly uses `num_predict` in native API options rather than supporting
  every OpenAI-specific option identically; verify JSON response format support for
  the chosen Ollama version/model. The adapter sends OpenAI-compatible
  `max_tokens`/`response_format` fields and does not silently retry via a different
  API. Non-Ollama endpoints may require an API key.
- Provide text generation and JSON-mode response requests. The HTTP adapter bounds
  response size, applies socket timeouts, and reports status/transport failures
  without logging prompts, API keys, or response bodies. Cancellation of a coroutine
  cannot forcibly terminate a request already running in a worker thread.
- Provide a structured intent resolver that accepts an application allowlist and
  validates the model response shape, allowed intent name, parameter object, and
  confidence range. An intent is only a proposal: it does not authorize or execute
  an action. Applications must validate parameters against their own business
  schemas and perform authorization through the normal capability/resource boundary.
  Initialize `AISubsystem` before `IntentSubsystem`; the latter resolves the already
  initialized model provider from the dependency container.
- Provide a process-local memory provider with a configurable message-count bound.
  Conversation count and message length are bounded as well. Every read and write
  requires a trusted execution context matching the tenant and actor, and is scoped
  by conversation. This baseline is not durable; a persistent memory provider can
  implement the same contract.

  ```yaml
  memory:
    provider: in_memory
    config:
      max_messages: 50
      max_conversations: 100
      max_message_chars: 10000
  ```

- Provide an optional keyword-based knowledge provider with tenant filtering,
  optional actor ACLs, explicit source allowlists, and source citations. Retrieved
  retrieval requires trusted context matching the supplied tenant and actor.
  Retrieved content is untrusted input, not instructions. The in-memory provider is
  for tests and small demos; document count and content length are bounded. It does
  not provide embeddings, chunking, durable/vector storage, or document ingestion
  pipelines. Document indexing/deletion are administrative operations and must be
  exposed only through application code that authorizes the source and tenant.

  ```yaml
  knowledge:
    provider: in_memory_keyword
    config:
      max_documents: 1000
      max_document_chars: 100000
  ```
- Keep tool execution, model-driven side effects, autonomous agents, and automatic
  authorization out of this phase. Model tool calling can be added only with
  application-owned schemas, capability checks, and any required user confirmation.

#### Exit criteria

- an application can inject a model provider into a flow without making the flow
  runtime depend on a model SDK or bypassing authorization
- malformed or out-of-allowlist model intents are rejected and no intent can execute
  a capability directly
- memory reads cannot cross tenant, actor, or conversation boundaries
- knowledge retrieval applies tenant, actor, and allowed-source filters before
  returning source-linked citations
- model-provider timeout and HTTP failures are surfaced, with no default prompt or
  credential logging
- no hosted model, embedding, vector database, or additional SDK is required to run
  the core test suite

### Phase 6 — P2P subsystem (P2)

#### Deliverables

- peer identity, append-only message-store, and exchange transport contracts
- local-first messaging service with SQLite-backed durable message log
- in-memory transport for deterministic offline/reconnect and conflict tests

#### Scope

- Keep P2P optional and outside the server kernel. The message service can persist
  locally while a peer is unavailable, and synchronization can be retried later.
- Use stable message IDs and immutable message contents. Merge is idempotent for an
  identical ID/content pair; reusing an ID with different content is a hard conflict,
  never last-write-wins. Messages are displayed in deterministic
  `(created_at, message_id)` order.
- Keep the first transport in-process and test-only to validate APIs and offline
  semantics without choosing a network protocol. A future network transport must
  authenticate peer identity, bound/validate wire payloads, encrypt traffic where
  required, and defend against replay and unauthorized tenant/conversation sync.
- `ConfiguredPeerIdentityProvider` is a development identity only, not a cryptographic
  device identity. The transport-neutral foundation does not yet deliver messages
  across processes or machines and must not be deployed as a secure P2P system.
- The SQLite message store uses the application's already-initialized `Database`
  provider, so configure/start the database subsystem before the P2P subsystem.
  Supply a stable, application-assigned peer ID:

  ```yaml
  p2p:
    identity:
      peer_id: device-a
    message_store: {}
    transport: {}
  ```

  `InMemoryPeerTransport` is intentionally a test fixture and is not the runtime
  transport. Application routes/services must enforce user authorization before
  sending or exposing local messages; the local-first service is not an identity or
  authorization system.

#### Exit criteria

- sending persists to the local SQLite log before synchronization is attempted
- offline peers leave local messages intact; reconnect synchronization converges and
  can be safely repeated
- duplicate messages are idempotent and same-ID conflicting content is rejected
- peer identity/storage/transport are replaceable contracts, and no network transport
  or peer service is required by the kernel
- deployment-grade peer authentication, discovery, encryption, and cross-process
  networking remain explicitly out of scope for this foundation slice

## 3. Enhancement suggestions to the plan

These are the key enhancements I recommend adding to the architecture before implementation begins.

### 3.1 Add explicit execution policies to the flow runtime

The existing plan correctly notes that async I/O alone is not enough for CPU-heavy AI or ML work. This should be formalized.

Recommended contract:

```python
from enum import Enum

class ExecutionPolicy(str, Enum):
    ASYNC = "async"
    THREAD = "thread"
    PROCESS = "process"
    SYNC = "sync"
```

Then each flow step or subsystem operation can declare the policy it requires.

Recommended behavior:

- async I/O steps: direct async operations
- CPU-bound Python steps: thread pool or process pool depending on GIL and resource profile
- native inference or GPU workloads: dedicated worker or external service
- heavy tasks: explicit isolation and bounded queueing

This avoids forcing all developers to understand Starlette internals or ad hoc worker configuration.

### 3.2 Separate identity, authorization, and execution context

The current design is strong, but the security boundary should be made explicit.

Suggested model:

- `ExecutionContext`: request ID, trace ID, tenant ID, actor ID, cancellation state, metadata
- `AuthorizationService`: checks whether the actor may perform an action
- `PolicyEngine`: enforces capability and resource constraints
- `ContextPropagation`: handles async propagation only, not security decisions

This is important because a context variable is not itself a trust boundary.

### 3.3 Add provider-specific concurrency defaults to SQLite

The document’s concern about SQLite concurrency is valid and should be turned into concrete defaults in the SQLite provider.

Recommended initial SQLite defaults:

```yaml
database:
  provider: sqlite
  sqlite:
    path: ./data/app.db
    journal_mode: WAL
    busy_timeout_ms: 30000
    foreign_keys: true
    connection_limit: 10
```

And runtime safeguards:

- short write transactions
- retry behavior for `SQLITE_BUSY`
- bounded concurrency for write access
- use `aiosqlite` or equivalent async integration at the provider layer
- document when PostgreSQL is the correct choice for multi-writer workloads

### 3.4 Introduce observability contracts from day one

The architecture discusses observability but should define it as a deliberate runtime concern.

Recommended metrics and traces:

- request duration
- subsystem initialization time
- flow step execution time
- worker wait time
- timeout/cancellation count
- database lock waits
- provider failures and retry counts
- tenant and request correlation IDs

Sensitive data should never be logged by default.

### 3.5 Keep provider registrations explicit and safe

The provider registry should remain a registry, not a dynamic plugin loader.

Recommended rules:

- only registered provider classes may be used
- provider name must be unique within a subsystem
- provider validation must happen at startup
- compatibility checks should verify declared contract support
- dynamic third-party loading should be deferred until the security model is proven

### 3.6 Treat transport identity as untrusted

HTTP headers and other client-controlled request fields may provide hints or requested values, but they must not establish an authenticated actor or trusted tenant on their own.

Recommended boundary:

- authenticate the caller in the HTTP/application layer
- populate trusted actor and tenant claims only from verified credentials or a trusted upstream identity provider
- authorize every capability and resource operation independently of `ExecutionContext`
- enforce tenant scoping at the relevant data-access or capability boundary
- reject or explicitly handle missing identity; do not silently grant a system or anonymous identity more access

Context variables carry execution data; they are not proof of identity and are not an authorization mechanism.

### 3.7 Make subsystem startup transactional

Startup can fail after some subsystems have already acquired resources. Track successfully initialized subsystems and, if a later initialization fails, shut down the successful ones in reverse initialization order before surfacing the original startup failure. Preserve cleanup failures as diagnostics without hiding the startup error.

Lifecycle behavior should also define whether repeated shutdown is safe and what happens when a subsystem's shutdown fails. Only successfully initialized subsystems should be shut down.

### 3.8 Validate configuration with explicit schemas

Give runtime, subsystem, and provider configuration defined schemas and validation rules. Reject unknown keys where appropriate, invalid values, missing required settings, and unsupported provider/contract combinations with actionable errors at startup.

Document configuration precedence and secret handling. Secrets should come from environment variables or a designated secrets provider, not committed configuration. Environment-variable overrides should have a documented, deterministic mapping to configuration fields.

Avoid binding the public configuration API to an implementation-specific schema library unless that dependency is justified; the important requirements are stable validation behavior and useful errors.

### 3.9 Make retries safe by design

Retries can repeat external side effects when a timeout or connection failure leaves the operation outcome uncertain. Before adding automatic retry behavior:

- classify errors as retryable, non-retryable, or outcome-unknown
- restrict retries to operations whose semantics make repetition safe
- define idempotency-key support for side-effecting operations where retries are needed
- use bounded attempts, backoff, and an overall deadline
- ensure cancellation stops future retries

Start with in-process flows. Defer durable or resumable execution until a demonstrated use case requires it.

### 3.10 Define readiness and graceful shutdown

Expose separate liveness and readiness semantics. Liveness indicates that the process is running; readiness indicates that required startup work and configured critical subsystems are healthy enough to serve traffic.

During shutdown, stop accepting new work, allow in-flight requests or flows a bounded drain period, then cancel or time out remaining work and release subsystem resources. Report failures rather than silently treating partial cleanup as success.

### 3.11 Make tenant isolation an end-to-end invariant

Test tenant isolation across the full path from authenticated request through capability authorization to database access. Include concurrent requests for different tenants, missing identity, forged tenant headers, direct service/data-access calls, and attempts to use context values to change access. Every data-access path must apply tenant scoping or prove why it is not applicable.

### 3.12 Defer plugin discovery

Keep `plugins/` as a future packaging and extension boundary, not an early runtime feature. Initially, applications should import and register trusted providers and subsystems explicitly. Do not scan directories or load arbitrary code automatically.

Before adding third-party plugin discovery, specify trust and installation rules, compatibility/versioning, configuration validation, startup-failure isolation, and the security impact of executing plugin code in-process.

## 4. Proposed future project structure

The tree below is a target layout to make package responsibilities and dependencies visible. It is intentionally illustrative: create directories and packages when a working feature needs them, not just to fill out the tree. Phase 1 remains focused on the kernel under `xyberos/kernel/`.

```text
xyberos/
├── pyproject.toml
├── README.md
├── docs/
│   ├── xyberos2.0.md
│   └── implementation.md
├── xyberos/
│   ├── __init__.py
│   ├── kernel/                         # Framework-independent runtime and contracts
│   │   ├── __init__.py
│   │   ├── contracts.py                # Subsystem, Provider, Capability, context contracts
│   │   ├── runtime.py                  # Kernel bootstrap and shutdown orchestration
│   │   ├── container.py                # Explicit dependency registration and resolution
│   │   ├── config.py                   # Configuration loading, normalization, validation
│   │   ├── registry.py                 # Subsystem/provider/capability registries
│   │   ├── context.py                  # ExecutionContext and context propagation
│   │   ├── lifecycle.py                # Startup/shutdown ordering and lifecycle state
│   │   ├── policies.py                 # Policy interfaces and enforcement contracts
│   │   ├── security.py                 # Trusted principal contracts and guarded capability entry points
│   │   ├── events.py                   # In-process event bus contract/implementation
│   │   ├── errors.py                   # Stable public kernel exceptions
│   │   └── observability.py            # Logging/trace/metrics hooks, without app-specific sinks
│   ├── subsystems/                     # Optional capability groups and their public APIs
│   │   ├── database/
│   │   │   ├── __init__.py
│   │   │   ├── contracts.py            # Database/repository/transaction interfaces
│   │   │   └── subsystem.py            # Database subsystem lifecycle and provider selection
│   │   ├── flows/
│   │   │   ├── __init__.py
│   │   │   ├── contracts.py            # Typed flow and step interfaces
│   │   │   ├── engine.py               # Deterministic execution, branches, retries, timeout
│   │   │   └── execution.py            # Async/thread/process execution policies
│   │   ├── ai/
│   │   │   ├── contracts.py            # Model message, response, and provider contract
│   │   │   ├── intent.py               # Validated model intent proposals
│   │   │   └── subsystem.py            # Model provider selection and lifecycle
│   │   ├── knowledge/
│   │   │   ├── contracts.py            # Tenant-scoped retrieval and citation contract
│   │   │   └── subsystem.py            # Knowledge provider lifecycle
│   │   ├── memory/
│   │   │   ├── contracts.py            # Tenant/actor/conversation-scoped memory
│   │   │   └── subsystem.py            # Memory provider lifecycle
│   │   ├── p2p/
│   │   │   ├── contracts.py            # Peer identity, append-only messages, transport
│   │   │   ├── messaging.py            # Local-first send and explicit peer sync
│   │   │   └── subsystem.py            # Peer messaging provider lifecycle
│   │   └── blob/                       # Optional file/blob storage API
│   ├── providers/                      # First-party implementations of subsystem contracts
│   │   ├── database/
│   │   │   ├── sqlite.py
│   │   │   └── postgresql.py
│   │   ├── blob/
│   │   │   ├── local_filesystem.py
│   │   │   └── s3_compatible.py
│   │   ├── ai/
│   │   │   └── openai_compatible.py    # Hosted or local Chat Completions adapter
│   │   ├── knowledge/
│   │   │   └── in_memory.py            # Demo/test keyword retrieval provider
│   │   ├── memory/
│   │   │   └── in_memory.py            # Bounded process-local conversation history
│   │   └── p2p/
│   │       ├── local_identity.py       # Configured demo identity
│   │       ├── sqlite_message_store.py # Durable append-only local message log
│   │       └── in_memory_transport.py  # Test-only multi-peer transport
│   ├── plugins/                        # Optional, explicitly registered extension packages
│   │   ├── __init__.py
│   │   └── ...                         # Add only when a real extension needs this boundary
│   ├── middleware/                     # Framework-neutral request/execution middleware contracts
│   │   ├── __init__.py
│   │   └── ...                         # Avoid framework imports in the kernel
│   ├── http/                           # Starlette/ASGI adapter; framework-specific code lives here
│   │   ├── __init__.py
│   │   ├── app.py
│   │   ├── authentication.py           # HTTP authentication integration and verified identity mapping
│   │   ├── middleware.py               # Starlette middleware bridging requests to kernel context
│   │   ├── dependencies.py             # ASGI request dependencies and kernel access
│   │   └── routes.py                   # HTTP routing helpers, not application business routes
│   └── modules/                        # Reusable application features built on subsystem APIs
│       └── ...                         # e.g. messaging, forums; not kernel responsibilities
├── apps/
│   ├── example_crud_app/               # First traditional application vertical slice
│   ├── example_ai_app/                 # Later optional AI-enabled example
│   └── example_p2p_app/                # Later optional P2P proof of concept
└── tests/
    ├── unit/
    ├── contracts/
    ├── integration/
    ├── security/
    └── end_to_end/
```

### 4.1 Directory responsibilities and boundaries

| Location | Belongs here | Must not become |
| --- | --- | --- |
| `xyberos/kernel/` | Runtime lifecycle, configuration, dependency container, registries, context propagation, policy and event contracts, stable kernel errors | A home for Starlette, SQL queries, model SDKs, UI, or application business rules |
| `xyberos/subsystems/` | Capability-level interfaces and orchestration, such as database, flows, AI, blob, and P2P | A duplicate provider implementation or a mandatory dependency for every app |
| `xyberos/providers/` | Concrete implementations selected by a subsystem, such as SQLite, PostgreSQL, or local blob storage | A place for app-specific business workflows |
| `xyberos/plugins/` | Optional, explicitly registered bundles that contribute providers, subsystems, or application modules | An unrestricted directory scanner or implicit execution mechanism |
| `xyberos/middleware/` | Framework-neutral middleware concepts and reusable execution-boundary behavior | Starlette/ASGI request or response objects |
| `xyberos/http/` | Starlette/ASGI app wiring, HTTP adapters, request parsing, and framework-specific middleware | Kernel contracts or business logic |
| `xyberos/modules/` | Reusable application features composed from kernel and subsystem APIs | Core runtime responsibilities |
| `apps/` | Runnable applications that prove the public APIs work together | Shared platform implementation |
| `tests/` | Unit, contract, integration, security, and end-to-end tests grouped by scope | Product runtime code |

### 4.2 Provider versus plugin

A provider is one implementation of a subsystem contract—for example, the SQLite implementation of the database subsystem. A plugin is an optional packaging/registration boundary that may contribute one or more providers, subsystems, or modules. A provider does not have to be a plugin, and first-party providers should initially be imported and registered explicitly by the application.

Do not implement automatic plugin discovery or arbitrary code loading in the first release. If plugin support is introduced later, define a trust, version-compatibility, configuration-validation, and failure-isolation model before enabling it.

### 4.3 Middleware versus HTTP adapter

Use `xyberos/middleware/` only for middleware that can remain independent of a particular web framework. Put Starlette-specific ASGI middleware—including the adapter that establishes and resets `ExecutionContext` around a request—in `xyberos/http/middleware.py`. This keeps the kernel and reusable middleware free of Starlette imports while retaining a clear place for the current HTTP integration.

### 4.4 Dependency direction

The intended dependency direction is:

```text
apps and application modules
        ↓
HTTP adapters and optional subsystems
        ↓
kernel contracts and runtime
```

Providers implement subsystem contracts; the kernel should not import concrete providers. The kernel must not import `xyberos/http`, Starlette, SQLite libraries, AI SDKs, or P2P libraries. Optional subsystems and providers should be importable only when an application enables or registers them.

### 4.5 Security placement

Security is a cross-cutting platform responsibility, not an optional subsystem that applications can accidentally omit from protected operations.

- `xyberos/kernel/security.py` owns framework-independent principal contracts and the mandatory guarded capability-execution boundary. `policies.py` owns policy interfaces/implementations where separation remains useful.
- `xyberos/http/authentication.py` adapts the application's chosen authentication mechanism and maps verified credentials to a trusted principal. It must not treat client-supplied actor or tenant headers as proof of identity.
- `xyberos/http/middleware.py` establishes and resets request execution context from that authenticated principal; request IDs and other transport metadata remain untrusted correlation data.
- Subsystems and data-access boundaries enforce resource-level authorization and tenant scoping. Kernel policy checks do not replace domain/database checks.
- Authentication mechanisms may be replaceable; protected capability execution must still pass through authorization and policy enforcement.

Phase 2 establishes and tests the trusted HTTP-to-context identity boundary and tenant-scoped CRUD access. The generic capability execution pipeline is a kernel security deliverable that must be completed before application capabilities are exposed as public APIs; it is not implied to be complete merely because an authentication adapter or `PolicyEngine` contract exists.

The Phase 2 HTTP adapter intentionally does not prescribe or implement a token/session scheme. The application must inject an identity resolver backed by its chosen authentication mechanism; if none is configured or no verified identity is returned, protected routes reject the request.

## 5. Recommended starter configuration

```yaml
xyberos:
  runtime:
    environment: development

  http:
    framework: starlette

  subsystems:
    database:
      enabled: true
      provider: sqlite
      config:
        path: ./data/app.db
        journal_mode: WAL
        busy_timeout_ms: 30000

    flows:
      enabled: true
      execution:
        max_concurrent_runs: 100
      config:
        default_timeout_seconds: 30

    ai:
      enabled: false

    knowledge:
      enabled: false

    memory:
      enabled: false

    blob:
      enabled: false

    p2p:
      enabled: false
```

## 6. Testing plan

### Required test categories

- kernel unit tests
  - lifecycle management
  - partial-startup rollback and reverse-order cleanup
  - repeated shutdown and shutdown failures
  - registry behavior
  - dependency resolution
  - context propagation
  - configuration schema validation and actionable errors

- provider contract tests
  - SQLite write/read behavior
  - lock timeout handling
  - provider interface conformance

- integration tests
  - Starlette + kernel + database interaction
  - request context propagation through middleware
  - liveness/readiness behavior and bounded graceful shutdown

- flow tests
  - sequential execution
  - timeouts
  - cancellation
  - bounded retry/backoff behavior
  - idempotent side effects and outcome-unknown failures
  - structured failure reporting

- security tests
  - forged tenant or actor headers cannot establish trusted identity or bypass policy checks
  - context values cannot escalate privileges
  - tenant isolation holds across concurrent requests and direct data-access paths
  - unauthorized resource access is rejected

- lifecycle tests
  - clean shutdown
  - worker cleanup
  - connection cleanup

## 7. Suggested first implementation task list

### Sprint 1

1. Define kernel contracts and container
2. Implement execution context with `contextvars`
3. Add subsystem bootstrap with startup rollback and reverse-order shutdown
4. Add middleware that carries request metadata without trusting identity headers
5. Define configuration validation and secret-handling rules
6. Build SQLite provider with WAL and busy timeout defaults
7. Add a minimal sample endpoint and test it with authenticated identity

### Sprint 2

1. Add flow engine with typed steps
2. Add execution policy enum and worker assignment rules
3. Add timeout, cancellation, bounded retry, idempotency, and trace behavior
4. Validate concurrent request and tenant isolation
5. Add liveness/readiness and graceful shutdown behavior

### Sprint 3

1. Add PostgreSQL provider contract and tests
2. Add blob storage abstraction and local filesystem provider
3. Add security policy enforcement checks
4. Document deployment and provider configuration guidance
5. Keep plugin loading out of scope until trust and compatibility requirements are specified

## 8. Final assessment

The architecture in [docs/xyberos2.0.md](./docs/xyberos2.0.md) is sound and correctly prioritizes a simple server-based kernel plus optional subsystems. The strongest implementation improvements are:

- explicit flow execution policies
- strict separation between execution context and authorization
- concrete SQLite concurrency defaults and retries
- observability built into the runtime from the start
- startup rollback, trusted identity boundaries, and end-to-end tenant isolation
- explicit configuration validation, readiness, and graceful shutdown
- deferred plugin discovery and retry safety based on idempotency

If these are added early, Xyberos 2.0 stays lightweight, testable, and production-minded while still leaving room for AI, flow orchestration, and optional P2P features later.
