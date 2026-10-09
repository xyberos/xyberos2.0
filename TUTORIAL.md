# Xyberos 2.0 Tutorial

This guide walks through the current APIs: setting up the kernel and SQLite
subsystem, attaching trusted identity to HTTP requests, adding liveness/readiness
routes and request draining, and making an optional policy-checked model call.

For installation, supported Python versions, project layout, and limitations, see
the [README](README.md). Code samples assume commands are run from the repository
root.

## 1. Install and test

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
python -m unittest discover -s tests -p "test_*.py"
```

No model server is needed for the tests or the database example.

## 2. Create a kernel with SQLite

Subsystems own initialization and cleanup; providers implement the concrete
storage/API contract. Configure the provider explicitly, register its subsystem,
then bootstrap the kernel:

```python
from xyberos.kernel import XyberosKernel
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.database import DatabaseSubsystem

provider = SQLiteProvider()
kernel = XyberosKernel(
    {
        "xyberos": {
            "subsystems": {
                "database": {
                    "enabled": True,
                    "provider": "sqlite",
                    "config": {
                        "path": "./data/tutorial.db",
                        "journal_mode": "WAL",
                        "busy_timeout_ms": 30_000,
                    },
                }
            }
        }
    }
)
kernel.register_subsystem("database", DatabaseSubsystem(provider))

await kernel.bootstrap()
```

After bootstrap, the `Database` contract is registered in the dependency
container. Create application-owned tables and use parameterized statements:

```python
from xyberos.subsystems.database import Database

database = kernel.container.resolve(Database)
await database.execute(
    """
    CREATE TABLE IF NOT EXISTS notes (
        id TEXT PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        body TEXT NOT NULL
    )
    """
)
await database.execute(
    "INSERT INTO notes (id, tenant_id, body) VALUES (?, ?, ?)",
    ("note-1", "tenant-demo", "First note"),
)
rows = await database.fetch_all(
    "SELECT id, body FROM notes WHERE tenant_id = ? ORDER BY id",
    ("tenant-demo",),
)
```

Close the kernel in a `finally` block so initialized subsystems release resources:

```python
try:
    # Serve requests or execute application work.
    ...
finally:
    await kernel.shutdown()
```

SQLite's default path is `./data/app.db`; file-backed databases default to WAL.
The provider creates the parent directory. The example application's schema is
created by its Starlette lifespan, not by `DatabaseSubsystem`.

## 3. Keep tenant identity trusted

HTTP middleware accepts identity only from an injected authentication resolver.
The resolver should validate a session, signed token, or another trusted
credential, then return an `AuthenticatedIdentity`:

```python
from xyberos.kernel.security import AuthenticatedIdentity


async def resolve_identity(request):
    principal = await your_authentication_service.authenticate(request)
    if principal is None:
        return None
    return AuthenticatedIdentity(
        actor_id=principal.user_id,
        tenant_id=principal.tenant_id,
    )
```

`your_authentication_service` represents application-owned authentication code;
it is not a Xyberos function. Never use `x-tenant-id` or `x-actor-id` directly as
trusted identity. `XyberosContextMiddleware` creates an `ExecutionContext` after
the resolver succeeds and clears it when the request finishes.

The CRUD reference app uses this middleware. Its runnable local-only entry point
is `apps.example_crud_app.demo`; it has a fixed demo credential, not real
authentication.

```python
from apps.example_crud_app.app import create_app
from xyberos.kernel.security import AuthenticatedIdentity

# Demo-only token mapping. Replace this with real authentication before deployment.
DEMO_IDENTITIES = {
    "Bearer demo-alice": AuthenticatedIdentity("alice", "tenant-a"),
}


async def resolve_identity(request):
    return DEMO_IDENTITIES.get(request.headers.get("authorization"))


app = create_app(
    identity_resolver=resolve_identity,
    database_path="./data/tutorial-crud.db",
)
```

Run the custom app you created, or use the built-in local-only demo:

```powershell
python -m uvicorn tutorial_app:app --reload
```

Alternatively, launch the bundled demo (its only credential is for local
demonstration and is not real authentication):

```powershell
python -m uvicorn apps.example_crud_app.demo:app --reload
```

The public health endpoints work without a credential:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health/live
Invoke-RestMethod http://127.0.0.1:8000/health/ready
```

For the bundled demo, set its local-only credential and create/list an item:

```powershell
$headers = @{ Authorization = "Bearer demo-alice" }
# Override the custom-app credential when using the bundled demo entry point.
$headers = @{ Authorization = "Bearer xyberos-local-demo" }
$item = Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/items `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"title":"First item"}'

$item
Invoke-RestMethod -Uri http://127.0.0.1:8000/items -Headers $headers
```

The example's SQL always filters rows by the authenticated tenant. The demo token
is not a secure credential; do not expose this resolver outside local development.
The reference app includes kernel admission middleware: requests receive `503`
before startup or after shutdown, while health routes remain available to report
the lifecycle and the configured database dependency probe. Readiness probes are
application-supplied async callables and each is bounded to one second by default.
See the [deployment runbook](docs/deployment.md) for schema migration, backup,
restore, and operational guidance.

## 4. Execute a guarded application capability

Register each public capability with its handler before kernel startup, and
register an application-owned policy. Invoke the operation through the kernel;
the executor requires a trusted execution context, checks policy, then calls the
handler. Keep resource authorization and tenant filters in the handler as well:
the policy check does not replace domain or data-access enforcement.

```python
from xyberos.kernel import (
    Capability,
    ExecutionContext,
    ExecutionContextAccessor,
    PolicyEngine,
)
from xyberos.subsystems.database import Database


class ItemsPolicy(PolicyEngine):
    async def authorize(
        self,
        context: ExecutionContext,
        capability: Capability,
        resource: object = None,
    ) -> bool:
        return (
            capability.name == "items.list"
            and bool(context.actor_id.strip())
            and bool(context.tenant_id.strip())
        )


async def list_tenant_items():
    context = ExecutionContextAccessor.get()
    database = kernel.container.resolve(Database)
    return await database.fetch_all(
        "SELECT id, title FROM items WHERE tenant_id = ? ORDER BY title, id",
        (context.tenant_id,),
    )


# Do this before `await kernel.bootstrap()`.
kernel.register_capability(Capability("items.list"), list_tenant_items)
kernel.container.register_utility(PolicyEngine, ItemsPolicy())

# Call from a route after XyberosContextMiddleware has established trusted context.
items = await kernel.execute_capability("items.list")
```

The executor denies missing context or policy, unregistered capabilities, and
policy denials. A capability marked `requires_authentication=False` still requires
a context and explicit policy decision; it only omits the executor's non-empty
actor/tenant check. The application policy must explicitly decide whether that
context is allowed. Calls through `execute_capability` are tracked as active kernel
work and are drained during shutdown. Direct calls to handlers bypass this boundary.

## 5. Add health routes and graceful HTTP admission

`create_health_routes(kernel)` builds `GET /health/live` and `GET /health/ready`.
`KernelAdmissionMiddleware` tracks requests while the kernel is running and returns
`503` for new application requests during startup or shutdown. It excludes those
two default health paths so probes can still read state:

```python
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from xyberos.http.health import create_health_routes
from xyberos.http.middleware import KernelAdmissionMiddleware
from xyberos.kernel import XyberosKernel

kernel = XyberosKernel(
    {
        "xyberos": {
            "runtime": {"shutdown_drain_timeout_seconds": 20},
            "subsystems": {},
        }
    }
)


async def index(request: Request) -> JSONResponse:
    return JSONResponse({"ready": request.app.state.kernel.health.ready})


@asynccontextmanager
async def lifespan(app):
    await kernel.bootstrap()
    try:
        yield
    finally:
        await kernel.shutdown()


app = Starlette(
    routes=[
        *create_health_routes(kernel),
        Route("/", index),
    ],
    lifespan=lifespan,
)
app.state.kernel = kernel
app.add_middleware(KernelAdmissionMiddleware, kernel=kernel)
```

For another app, use the same `kernel` instance for subsystem setup, lifespan
bootstrap/shutdown, health routes, and middleware. If changing the health route
prefix, pass the matching full paths through the middleware's `excluded_paths`.

`kernel.work()` is also available to track non-HTTP work:

```python
async with kernel.work():
    await perform_application_work()
```

Shutdown first stops new work admissions, then waits for tracked work for the
configured timeout (30 seconds by default). A `ShutdownDrainTimeoutError` leaves
subsystems open and the kernel in `STOPPING`; finish or cancel remaining work and
retry `await kernel.shutdown()`. The kernel does not forcibly terminate arbitrary
tasks, threads, or processes. Liveness/readiness only report lifecycle state; they
do not check database or model-server health.

## 6. Configure optional Ollama model generation

The OpenAI-compatible provider defaults to the local Ollama endpoint and `llama3.2`.
Install Ollama separately, start the service, and pull the model:

```powershell
ollama pull llama3.2
```

The bundled demo entry point has an optional `POST /ai/generate` endpoint wired to
that provider and a policy restricted to the demo identity. After starting
`apps.example_crud_app.demo`, call it with the demo credential:

```powershell
$headers = @{ Authorization = "Bearer xyberos-local-demo" }
Invoke-RestMethod `
  -Method Post `
  -Uri http://127.0.0.1:8000/ai/generate `
  -Headers $headers `
  -ContentType "application/json" `
  -Body '{"prompt":"Give me a one-sentence greeting."}'
```

Ollama is not required to run the default test suite or CRUD routes. To enable AI in
your own `create_app` instance, pass both a `ModelProvider` and an application-owned
`PolicyEngine`; the `/ai/generate` route is absent unless both are supplied.
Requests use the same trusted identity middleware as CRUD, and the guarded model
facade checks `ai.generate` before calling the provider.

Register a policy engine before starting `AISubsystem`. This example policy allows
all `ai.generate` requests and is **only for illustrating wiring**; production
policy must check the authenticated actor, tenant, and requested resource:

```python
from xyberos.kernel import (
    Capability,
    ExecutionContext,
    PolicyEngine,
    XyberosKernel,
)
from xyberos.providers.ai import OpenAICompatibleProvider
from xyberos.subsystems.ai import AISubsystem, ModelMessage, ModelProvider
from xyberos.kernel.contracts import ExecutionContextAccessor


class DemoPolicy(PolicyEngine):
    async def authorize(
        self,
        context: ExecutionContext,
        capability: Capability,
        resource=None,
    ) -> bool:
        return capability.name == "ai.generate"


provider = OpenAICompatibleProvider()
ai = AISubsystem(provider)
kernel = XyberosKernel(
    {
        "xyberos": {
            "subsystems": {
                "ai": {
                    "enabled": True,
                    "provider": "openai_compatible",
                    "config": {
                        "base_url": "http://localhost:11434/v1",
                        "model": "llama3.2",
                        "timeout_seconds": 30,
                        "max_input_chars": 100_000,
                        "max_output_tokens": 2_048,
                    },
                }
            }
        }
    }
)
kernel.container.register_utility(PolicyEngine, DemoPolicy())
kernel.register_subsystem("ai", ai)

await kernel.bootstrap()
try:
    # In an HTTP app, XyberosContextMiddleware sets this only after trusted auth.
    token = ExecutionContextAccessor.set(
        ExecutionContext(
            request_id="tutorial-request",
            tenant_id="tenant-demo",
            actor_id="actor-demo",
        )
    )
    try:
        model = kernel.container.resolve(ModelProvider)
        response = await model.generate(
            [ModelMessage(role="user", content="Give me a one-sentence greeting.")]
        )
        print(response.content)
    finally:
        ExecutionContextAccessor.reset(token)
finally:
    await kernel.shutdown()
```

`ModelProvider` resolved from the container is a guarded facade. It requires a
trusted execution context and policy approval for `ai.generate`; avoid passing the
raw provider directly into application flows. The snippet sets context manually to
make the example standalone. In a server, rely on authenticated middleware, not
caller-supplied IDs.

To use a hosted OpenAI-compatible endpoint, set `base_url` to that provider's
HTTPS `/v1` base URL, set `model` to an available model, and provide `api_key` via
your application's secret-management/configuration path. Do not place credentials
in source code or committed configuration. The provider does not automatically
retry with a vendor-specific API if an endpoint lacks a requested feature.

## 7. Manually pair devices for encrypted P2P messaging

Install the optional crypto dependency:

```powershell
python -m pip install -e ".[p2p-crypto]"
```

Each device has an Ed25519 signing key and a sealed-box encryption key. Provision
and persist both private keys in application-managed protected storage; do not
commit them or regenerate them on each start. Generate an identity once, save its
private keys securely, and exchange only the public bundle over a trusted channel:

```python
from xyberos.providers.p2p import SodiumPeerIdentityProvider

identity_a = SodiumPeerIdentityProvider()
await identity_a.initialize({"peer_id": "device-a"})
public_bundle_a = identity_a.public_keys.to_dict()
fingerprint_a = identity_a.public_keys.fingerprint

# Persist these values in a secret manager; never print or commit them.
signing_key_to_store = identity_a.signing_private_key.hex()
encryption_key_to_store = identity_a.encryption_private_key.hex()
await identity_a.close()
```

On later starts, load both private keys from that protected store and pass them
with the stable peer ID to `initialize`. Compare each device's public-key
fingerprint out of band before pinning the exchanged bundle. A fingerprint is
for comparison only; it does not provide key discovery, revocation, or recovery.

Configure the relay with the public bundles for both devices and a mutual allowlist.
The `Database` instance must already be initialized before `relay.initialize()`:

```python
from contextlib import asynccontextmanager

from starlette.applications import Starlette
from xyberos.providers.database import SQLiteProvider
from xyberos.providers.p2p import HTTPSRelayService, PeerPublicKeys

relay_database = SQLiteProvider()
trusted_peers = {
    "device-a": PeerPublicKeys.from_dict(public_bundle_a),
    "device-b": PeerPublicKeys.from_dict(public_bundle_b),
}
relay = HTTPSRelayService(
    database=relay_database,
    trusted_peers=trusted_peers,
    allowed_pairs={
        "device-a": ("device-b",),
        "device-b": ("device-a",),
    },
)


@asynccontextmanager
async def lifespan(app):
    await relay_database.initialize({"path": "./data/relay.db"})
    try:
        await relay.initialize()
        yield
    finally:
        await relay.close()
        await relay_database.close()


app = Starlette(routes=relay.routes, lifespan=lifespan)
```

Host that route behind TLS for any remote use. The transport rejects non-loopback
HTTP relay URLs; loopback HTTP exists only for local development and tests. Keep the
relay database and its lifecycle under the hosting application's control.

On each client, pass the other device's manually verified public bundle to the
transport and use the same local database for the message store and exact-envelope
retry cache. Register these providers as the P2P subsystem alongside the database
subsystem, with the database initialized first:

```python
from xyberos.providers.p2p import (
    HTTPSRelayTransportProvider,
    PeerPublicKeys,
    SodiumPeerIdentityProvider,
    SQLitePeerEnvelopeCache,
    SQLitePeerMessageStore,
)
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.database import DatabaseSubsystem
from xyberos.subsystems.p2p import OfflineMessagingService, P2PSubsystem

# `pinned_device_b` was exchanged and verified out of band.
database_provider = SQLiteProvider()
identity = SodiumPeerIdentityProvider()
store = SQLitePeerMessageStore(database_provider)
envelope_cache = SQLitePeerEnvelopeCache(database_provider)
transport = HTTPSRelayTransportProvider(
    identity,
    {"device-b": PeerPublicKeys.from_dict(pinned_device_b)},
    envelope_cache,
)
p2p = P2PSubsystem(identity, store, transport)
```

Enable it in kernel configuration. Private-key values below must come from your
secret store; remote relay URLs must use HTTPS:

```python
config = {
    "xyberos": {
        "subsystems": {
            "database": {
                "enabled": True,
                "provider": "sqlite",
                "config": {"path": "./data/device-a.db"},
            },
            "p2p": {
                "enabled": True,
                "identity": {
                    "peer_id": "device-a",
                    "signing_private_key": load_secret("device-a-signing-key"),
                    "encryption_private_key": load_secret("device-a-encryption-key"),
                },
                "message_store": {},
                "transport": {
                    "relay_url": "https://relay.example.net",
                    "timeout_seconds": 30,
                },
            },
        }
    }
}
```

Construct the kernel from that config, register both subsystems before startup,
then bootstrap:

```python
from xyberos.kernel import XyberosKernel

kernel = XyberosKernel(config)
kernel.register_subsystem("database", DatabaseSubsystem(database_provider))
kernel.register_subsystem("p2p", p2p)
await kernel.bootstrap()
```

After bootstrap, messages are saved locally first. Synchronization sends local
messages and merges authenticated messages from the selected pinned peer:

```python
messaging = kernel.container.resolve(OfflineMessagingService)
await messaging.send("conversation-1", "Hello from device A.")
await messaging.synchronize("device-b")
```

The relay stores ciphertext but can see peer IDs, message IDs, timestamps, sizes,
and traffic timing. The endpoint message store remains plaintext on each device.
The relay pages inboxes in batches of at most 100 envelopes, with a 4 MiB
per-request/response cap. Each device merges a page before persisting its local
cursor; if synchronization stops before that cursor is saved, the page is replayed
and idempotently merged on retry. This cursor is not a delivery receipt: the relay
retains messages append-only and does not delete them when a device advances.
Pairing is static, and there are no groups, key recovery, retention controls,
peer-level rate limits, or delivery acknowledgements. This is a protocol foundation,
not a managed messaging service. Plan retention, rate limits, backups, and key
recovery before exposing a relay to real users.

## 8. Where to go next

- Read [the implementation plan](docs/implementation.md) for each subsystem's
  maturity and operational constraints.
- Use [the architecture notes](docs/xyberos2.0.md) for the original design intent.
- Explore `tests/` for executable examples of lifecycle rollback, tenant isolation,
  flow retries/timeouts, provider contracts, AI policy checks, and local/relay P2P sync.

The in-memory P2P transport is still test-only. The HTTPS relay supports manually
paired one-to-one devices, but needs application-hosted TLS, secure device-key
storage, and operational retention/rate limits before production deployment. The
in-memory memory/knowledge providers are bounded baselines, not durable services.
