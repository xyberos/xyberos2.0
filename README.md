# Xyberos 2.0

Xyberos is an extensible Python application platform organized around a small
kernel, optional subsystems, and replaceable providers. The current implementation
includes a lifecycle-managed kernel, an async SQLite provider, a Starlette HTTP
adapter, a flow engine, optional AI/memory/knowledge/blob/P2P components, and an
example tenant-scoped CRUD application.

> **Status:** This is an evolving foundation, not a finished production framework.
> Read the security and limitations notes below before deploying it.

## Requirements

- Python 3.10 or newer
- Windows PowerShell, macOS, or Linux
- Ollama only if you want to run the default local AI provider

The core dependencies are Starlette and Uvicorn. SQLite is part of Python's
standard library. PostgreSQL support is optional.

## Install

From the project root, create and activate a virtual environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

For PostgreSQL support:

```powershell
python -m pip install -e ".[postgres]"
```

## Run the tests

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

The PostgreSQL integration test is skipped unless its test database is configured.
The normal test suite does not require Ollama or an external database.

## Start here

- **[Tutorial](TUTORIAL.md):** build a small app with the kernel, database, trusted
  request identity, health routes, graceful admission control, and optional Ollama.
- **[Deployment runbook](docs/deployment.md):** dependency readiness, schema
  migrations, TLS/secrets, backup and restore, shutdown, and provider maturity.
- **[Architecture review](ARCHITECTURE.md):** current runtime boundaries,
  lifecycle, request security, subsystem contracts, and operational limitations.
- **[Implementation plan](docs/implementation.md):** implemented phases, target
  structure, operational behavior, and remaining scope.
- **[Architecture notes](docs/xyberos2.0.md):** original platform goals and design.
- **[Public API policy](docs/public-api.md):** supported imports, Python matrix,
  versioning, and deprecation expectations.
- **[P2P threat model](docs/p2p-threat-model.md):** current relay protections,
  residual risks, and security decisions still awaiting review.

The example application is in [`apps/example_crud_app/`](apps/example_crud_app/).
Its routes show parameterized SQL and tenant scoping. It includes public health
routes and kernel admission/drain middleware. Run the intentionally local-only demo:

```powershell
python -m uvicorn apps.example_crud_app.demo:app --reload
```

The demo accepts the placeholder credential `Bearer xyberos-local-demo`; it is not
real authentication and must not be exposed outside local development. The default
`app` in `apps.example_crud_app.app` has no identity resolver, so its protected
data routes reject requests until an application supplies one.

Health routes are available without authentication:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

`/health/live` reports kernel lifecycle. `/health/ready` also runs any explicitly
configured bounded async dependency probes; it does not discover or probe
dependencies automatically. See the [deployment runbook](docs/deployment.md).

The local demo also enables `POST /ai/generate`; it requires a working Ollama
installation with `llama3.2` pulled. The library factory only enables that route
when both a model provider and an application policy engine are supplied.

## Project structure

```text
xyberos/
  kernel/       Runtime lifecycle, context, registries, policies, configuration
  http/         Starlette/ASGI authentication context, health and admission helpers
  subsystems/   Database, flows, AI, memory, knowledge, blob, and P2P contracts
  providers/    SQLite/PostgreSQL, Ollama-compatible AI, local blob, and other adapters
apps/
  example_crud_app/
tests/
docs/
```

Applications register the subsystem/provider implementations they trust. The
kernel does not discover or execute arbitrary plugins.

## Core usage shape

1. Construct providers and subsystems.
2. Configure `xyberos.subsystems` with subsystem-specific settings.
3. Register subsystems on `XyberosKernel`.
4. Register capabilities with handlers and an application-owned `PolicyEngine`
   before kernel startup when exposing guarded operations.
5. Register an application-owned `PolicyEngine` when using protected AI generation.
6. `await kernel.bootstrap()` before serving work.
7. `await kernel.shutdown()` during application teardown.

Invoke registered operations with `await kernel.execute_capability(...)` so the
kernel obtains trusted request context, consults policy, and tracks the operation
for graceful shutdown. Direct handler or service calls do not pass through this
authorization boundary; domain-level resource checks and tenant scoping are still
required inside the application.

See the tutorial for complete code samples and configuration details.

## Public API and versioning

The package exposes a small, stable root API for application code:

```python
import xyberos

print(xyberos.__version__)
from xyberos import kernel, http, providers, subsystems
```

This keeps the runtime entry points discoverable while leaving optional
subsystems and providers behind their own module boundaries. Public API stability
is intentionally focused on the kernel, HTTP adapter, and the subsystem/provider
contracts that applications actually depend on. Internal implementation details
remain free to change without forcing a breaking change across the framework.

When external integrations are added, they should follow a documented
compatibility policy: keep supported extension points explicit, deprecate in a
bounded way, and avoid promoting every internal helper to a long-term public API.
See the [public API policy](docs/public-api.md) for the supported surface and
release compatibility rules.

## Security notes

- `ExecutionContext` carries request-scoped metadata; it is **not itself
  authorization**.
- HTTP identity must come from a trusted `IdentityResolver` that returns
  `AuthenticatedIdentity`. Do not construct trusted identity from caller-controlled
  tenant or actor headers.
- The example's static identity mapping is suitable only for local demonstration.
  Replace it with your real authentication/session/token validation.
- The AI subsystem requires trusted execution context and an application-supplied
  policy engine before model requests are allowed. A model response is untrusted
  input; it cannot authorize or execute application actions.
- Supply hosted-provider credentials through a secret manager or environment-backed
  configuration. Do not commit credentials.
- Plain HTTP model endpoints are restricted to loopback addresses; remote model
  endpoints must use HTTPS.
- P2P currently provides a local-first synchronization foundation and an
  optional HTTPS relay for manually paired one-to-one devices. The relay route must
  be hosted by the application and configured with pinned peer keys.
- The [P2P threat model](docs/p2p-threat-model.md) is preliminary, not an
  independent cryptographic review or production approval.

## Current limitations

- The default AI provider points at Ollama (`http://localhost:11434/v1`) and model
  `llama3.2`; install/start Ollama and pull the model separately. Model availability
  and compatibility are not checked at kernel startup. The demo policy is for
  local testing only.
- In-memory memory and keyword-knowledge providers are bounded demo/test
  implementations, not durable vector search or document-ingestion services.
- The filesystem blob provider is local storage, not a cloud object-store adapter.
- P2P does not provide dynamic device discovery, group messaging, key rotation, or
  managed key recovery. The relay sees routing metadata and stores append-only
  ciphertext; its 100-envelope pages use local retry cursors, not delivery receipts
  or relay deletion. Protocol V2 applies configurable per-peer request and mailbox
  limits (defaults: 60 requests/minute with burst 10; 10,000 envelopes and 256 MiB
  of serialized envelope payload per recipient). This is not a total database-size
  cap. V1 is scheduled to retire on 2027-03-31; operators should migrate clients
  and relay configuration to V2 before that date and treat V1 as a transition-only
  compatibility path. Local device message storage is not encrypted at rest.
- Secure relay clients require the optional crypto extra:
  `python -m pip install -e ".[p2p-crypto]"`. See the tutorial for manual pairing
  and hosting guidance.
- Kernel liveness describes runtime lifecycle. Readiness can run application-
  configured dependency probes but does not discover dependencies automatically.
  Configure bounded checks and a deployment shutdown grace period accordingly.

## License

No license file is currently included. Confirm usage and redistribution rights
before distributing this project.
