# Xyberos 2.0 Tutorial for Beginners

Welcome! This tutorial is written in a simple, beginner-friendly style like W3Schools.

We will teach you in small steps:

- Start with the minimal setup
- Move to a real traditional app
- Learn P2P messaging
- Learn AI integration
- Keep each section separate so you are not overwhelmed

Before you start, read the project basics in [README.md](README.md).

This tutorial assumes you are inside the project root.

---

# 1. Install Xyberos

First, create a virtual environment and install the project.

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

Now run the test suite:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

If the tests pass, your environment is ready.

---

## 1.1 Big picture: kernel, subsystems, providers, HTTP, P2P, and flows

Xyberos is easier to understand if you think of it like a small operating system for your app.

### The main pieces

- Kernel: the boss that starts, runs, and stops everything.
- Subsystems: major feature groups such as database, HTTP, P2P, or flows.
- Providers: the actual implementation behind a subsystem, like SQLite or an in-memory peer transport.
- HTTP: the trusted request boundary between the outside world and your app.
- P2P: peer-to-peer messaging for devices or services that need offline-safe communication.
- Flows: named step-by-step business workflows that execute safely and predictably.

Think of it like this:

```text
browser / client
       |
       v
HTTP routes
       |
       v
Xyberos kernel
       |
   +--- subsystems (database, p2p, flows, etc.)
       |
   +--- providers (SQLite, relay, peer store, etc.)
```

### 1.1.1 What is the kernel?

The kernel is the main runtime object. It manages:

- lifecycle state
- dependency injection
- subsystem startup and shutdown
- execution context for requests
- capability execution

The simplest example is:

```python
from xyberos.kernel import XyberosKernel

kernel = XyberosKernel()
print(type(kernel).__name__)
```

The kernel does not contain your business logic. It is the organizer, not the app itself.

### 1.1.2 What is a subsystem?

A subsystem is a feature area. For example:

- database subsystem
- P2P subsystem
- flow subsystem
- AI subsystem

A subsystem usually wraps one or more providers and registers services into the dependency container.

```python
from xyberos.kernel import XyberosKernel
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.database import DatabaseSubsystem

kernel = XyberosKernel()
provider = SQLiteProvider()
subsystem = DatabaseSubsystem(provider)

kernel.register_subsystem("database", subsystem)
```

This does not start the subsystem yet. It only tells the kernel, "I have a database subsystem and here is its provider."

### 1.1.3 What is a provider?

A provider is the concrete implementation behind a subsystem.

Examples:

- SQLiteProvider for database storage
- InMemoryPeerTransport for quick P2P tests
- ConfiguredPeerIdentityProvider for a known peer ID
- HTTPSRelayTransportProvider for a relay-backed transport

Provider objects are usually initialized with configuration and then used by the subsystem.

```python
from xyberos.providers.database import SQLiteProvider

provider = SQLiteProvider()
await provider.initialize({"path": "./data/demo.db"})
print(provider.provider_name)
```

The important idea is:

- subsystem = the contract and lifecycle wrapper
- provider = the implementation behind the contract

### 1.1.4 How the kernel starts everything

A subsystem is initialized when the kernel bootstraps.

```python
kernel = XyberosKernel()
kernel.register_subsystem("database", DatabaseSubsystem(SQLiteProvider()))

await kernel.bootstrap({
    "xyberos": {
        "subsystems": {
            "database": {
                "enabled": True,
                "provider": "sqlite",
                "config": {"path": "./data/demo.db"},
            }
        }
    }
})
```

The config tells the kernel:

- enable the database subsystem
- use the `sqlite` provider
- pass the provider config

After bootstrap, the subsystem can resolve and use the provider through the dependency container.

### 1.1.5 How to use stored services from the container

Once the kernel is running, you can resolve services registered by the subsystem.

```python
from xyberos.subsystems.database import Database

# database = kernel.container.resolve(Database)
# await database.execute("SELECT 1")
```

This is the usual pattern in Xyberos:

1. register subsystem
2. bootstrap kernel with config
3. resolve services from `kernel.container`
4. use them safely inside your app

### 1.1.6 HTTP boundary

HTTP is how requests enter the app. Xyberos gives you HTTP middleware helpers so that only trusted identities become execution context.

```python
from starlette.applications import Starlette
from xyberos.http.middleware import XyberosContextMiddleware, KernelAdmissionMiddleware
from xyberos.http.health import create_health_routes
from xyberos.kernel.security import AuthenticatedIdentity

async def my_identity_resolver(request):
    token = request.headers.get("authorization")
    if token == "demo-token":
        return AuthenticatedIdentity(actor_id="alice", tenant_id="tenant-a")
    return None

app = Starlette()
app.add_middleware(XyberosContextMiddleware, identity_resolver=my_identity_resolver)
app.add_middleware(KernelAdmissionMiddleware, kernel=kernel)
app.router.routes.extend(create_health_routes(kernel))
```

In plain English:

- the request comes in through HTTP
- the identity resolver checks whether the caller is who they say they are
- if valid, Xyberos creates an `ExecutionContext`
- that context is then available to policy checks and safe internal code

This keeps untrusted HTTP input from directly becoming trusted app state.

### 1.1.7 P2P in plain English

P2P means peer-to-peer communication. This is useful when two devices need to exchange messages without always depending on a central app server.

Xyberos does not let raw messaging fly around freely. It keeps the P2P layer guarded and application-aware.

```python
from xyberos.providers.database import SQLiteProvider
from xyberos.providers.p2p import (
    ConfiguredPeerIdentityProvider,
    InMemoryPeerTransport,
    SQLitePeerMessageStore,
)
from xyberos.subsystems.p2p import P2PSubsystem

kernel = XyberosKernel()
db = SQLiteProvider()
await db.initialize({"path": ":memory:"})

identity = ConfiguredPeerIdentityProvider()
await identity.initialize({"peer_id": "device-a"})

transport = InMemoryPeerTransport()
await transport.initialize({})

store = SQLitePeerMessageStore(db)
await store.initialize({})

kernel.register_subsystem(
    "p2p",
    P2PSubsystem(identity_provider=identity, message_store=store, transport_provider=transport),
)
```

This creates a local peer identity, a local message store, and a transport layer. The subsystem is then initialized by the kernel at bootstrap time.

Important rule:

> Do not expose raw P2P messaging directly to app routes.

Instead, wrap it in a tenant-aware service that checks allowed peers, tenants, and conversations before sending or reading messages.

### 1.1.8 Flows

A flow is a named workflow made of steps. Each step does a small job, and the engine runs them in order with optional conditions, retries, or concurrency policies.

```python
from xyberos.subsystems.flows import FlowDefinition, FlowEngine, FlowStep

async def main():
    def load_value(state):
        return state.input

    def add_one(state):
        return state.outputs["load_value"] + 1

    flow = FlowDefinition(
        "demo-flow",
        (
            FlowStep("load_value", load_value),
            FlowStep("add_one", add_one),
        ),
    )

    result = await FlowEngine().run(flow, 10)
    print(result.state.outputs["add_one"])
```

This is a simple workflow:

1. take the input value
2. pass it into the next step
3. produce the final output

Flows are useful when a business process has several stages and you want clear logging, retries, and step-level control.

### 1.1.9 The big picture in one example

Here is a small end-to-end pattern:

```python
from xyberos.kernel import XyberosKernel
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.database import Database, DatabaseSubsystem

kernel = XyberosKernel()
provider = SQLiteProvider()
subsystem = DatabaseSubsystem(provider)

kernel.register_subsystem("database", subsystem)

await kernel.bootstrap({
    "xyberos": {
        "subsystems": {
            "database": {
                "enabled": True,
                "provider": "sqlite",
                "config": {"path": "./data/app.db"},
            }
        }
    }
})

# Later, inside your app code:
database = kernel.container.resolve(Database)
print("Kernel and database subsystem are ready.")
```

That is the core idea of Xyberos:

- build the app around a kernel
- attach subsystems
- connect providers
- enforce trust boundaries at HTTP and application layers
- use flows for multi-step work

### 1.1.10 Best practice reminders

- Keep the kernel small and focused.
- Register providers before bootstrapping.
- Use trusted identity resolution before making request-scoped decisions.
- Keep tenant boundaries strict.
- Do not expose raw low-level services directly to the public app layer.
- Start with one subsystem, then grow carefully.

Now that we understand the building blocks, let us move to a normal app example and then build up to P2P and AI patterns.

---

# 2. Traditional Apps Tutorial

This section teaches you how to build the normal app style: database + HTTP + tenant-scoped data.

## 2.1 Minimal traditional app

A traditional app usually needs:

- a kernel
- a database subsystem
- a trusted identity resolver
- HTTP routes

Here is the smallest useful example.

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
                        "path": "./data/demo.db"
                    },
                }
            }
        }
    }
)
kernel.register_subsystem("database", DatabaseSubsystem(provider))

await kernel.bootstrap()
```

### What this means

- `SQLiteProvider` gives you a database backend
- `DatabaseSubsystem` exposes the database contract
- `XyberosKernel` manages startup and shutdown

### Add a table

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
```

### Insert and read data

```python
await database.execute(
    "INSERT INTO notes (id, tenant_id, body) VALUES (?, ?, ?)",
    ("note-1", "tenant-a", "Hello Xyberos"),
)

rows = await database.fetch_all(
    "SELECT id, body FROM notes WHERE tenant_id = ? ORDER BY id",
    ("tenant-a",),
)
print(rows)
```

### Clean shutdown

```python
try:
    # app work here
    pass
finally:
    await kernel.shutdown()
```

---

## 2.2 Beginner traditional app with routes

Now let us build a small Starlette app with tenant-scoped data.

```python
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from xyberos.kernel import XyberosKernel
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.database import Database, DatabaseSubsystem

provider = SQLiteProvider()
kernel = XyberosKernel({
    "xyberos": {
        "subsystems": {
            "database": {
                "enabled": True,
                "provider": "sqlite",
                "config": {"path": "./data/tutorial.db"},
            }
        }
    }
})
kernel.register_subsystem("database", DatabaseSubsystem(provider))

async def create_table():
    database = kernel.container.resolve(Database)
    await database.execute(
        """
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            tenant_id TEXT NOT NULL,
            title TEXT NOT NULL
        )
        """
    )

async def list_items(request):
    database = kernel.container.resolve(Database)
    rows = await database.fetch_all(
        "SELECT id, title FROM items WHERE tenant_id = ? ORDER BY id",
        ("tenant-a",),
    )
    return JSONResponse({"items": rows})

async def startup():
    await kernel.bootstrap()
    await create_table()

app = Starlette(
    routes=[
        Route("/items", list_items, methods=["GET"]),
    ],
    on_startup=[startup],
)
```

### Why this matters

Real applications need relationship between:

- actor (who is making the request)
- tenant (whose data is being accessed)
- resource (the specific record)

This is where Xyberos enforces safe boundaries.

---

## 2.3 Trusted identity and tenant checks

A request is not trusted just because it contains a header.

Bad example:

```python
# Dangerous
# request.headers["x-tenant-id"]
```

Good example:

```python
from xyberos.kernel.security import AuthenticatedIdentity


def resolve_identity(request):
    token = request.headers.get("authorization")
    if token == "demo-token":
        return AuthenticatedIdentity(actor_id="alice", tenant_id="tenant-a")
    return None
```

### Rule

- Only a trusted authentication layer should create `AuthenticatedIdentity`
- Never trust caller-controlled tenant headers directly
- Always filter queries by the authenticated tenant

---

## 2.4 Advanced traditional app pattern

Now let us build a more realistic app:

- create item
- list item
- get item
- delete item
- use kernel capability execution with policy

The example app already exists here:

- [apps/example_crud_app/app.py](apps/example_crud_app/app.py)

Use it as a reference. It shows:

- startup and shutdown lifecycle
- health checks
- trusted execution context
- tenant-scoped database queries
- request validation

### Example flow

```python
from apps.example_crud_app.app import create_app

app = create_app(
    identity_resolver=my_identity_resolver,
    database_path="./data/example.db",
)
```

### Best practice

Keep business logic in application services. Keep policy checks at the boundary. Keep DB calls tenant-safe.

---

# 3. P2P Tutorial

This section is for peer-to-peer messaging. P2P in Xyberos is intentionally small and secure by design.

## 3.1 Minimal P2P setup

Start with the raw P2P primitives.

```python
from xyberos.providers.p2p import (
    ConfiguredPeerIdentityProvider,
    InMemoryPeerTransport,
)
from xyberos.providers.database import SQLiteProvider
from xyberos.providers.p2p import SQLitePeerMessageStore
from xyberos.subsystems.p2p import OfflineMessagingService

async def main():
    db = SQLiteProvider()
    await db.initialize({"path": ":memory:"})

    store = SQLitePeerMessageStore(db)
    await store.initialize({})

    identity = ConfiguredPeerIdentityProvider()
    await identity.initialize({"peer_id": "device-a"})

    transport = InMemoryPeerTransport()
    await transport.initialize({})

    messaging = OfflineMessagingService(identity, store, transport)
    message = await messaging.send("conversation-1", "hello from device-a")
    print(message)
```

### What this does

- creates a local peer identity
- stores messages locally
- sends a message in a conversation
- uses in-memory transport for offline sync tests

---

## 3.2 Beginner P2P pattern: offline message sync

P2P is useful when devices may be offline.

```python
# device A
message = await messaging_a.send("conversation-1", "offline note")

# device B is offline
# later, when online
count = await messaging_a.synchronize("device-b")
print(count)
```

### Important idea

The low-level P2P service stores messages locally and retries sync when peers reconnect.
This is good for offline-first apps, not as a full chat product by itself.

---

## 3.3 Secure application boundary

This is the important security rule for Phase 13:

> Do not expose raw `OfflineMessagingService` directly to application routes.

Instead, use a tenant-scoped wrapper.

```python
from xyberos.subsystems.p2p import TenantScopedMessagingService

secure_messaging = TenantScopedMessagingService(
    messaging,
    tenant_peer_map={
        "tenant-a": ("device-b",),
    },
    allowed_conversations={
        "tenant-a": ("conversation-1",),
    },
)
```

Then you can do:

```python
await secure_messaging.send_message(
    "tenant-a",
    "conversation-1",
    "hello from tenant-a",
)
```

### Why this wrapper is needed

It rejects:

- cross-tenant access
- disallowed conversations
- unauthorized peer IDs
- missing trusted execution context

This is the secure application boundary pattern.

---

## 3.4 Advanced P2P app pattern

Use the example app:

- [apps/example_p2p_app/app.py](apps/example_p2p_app/app.py)

It demonstrates:

- tenant scoped message routes
- read/send/sync endpoints
- restricted peer access
- application-layer authorization before raw P2P access

### Example route concept

```text
POST /tenants/{tenant_id}/conversations/{conversation_id}/messages
GET /tenants/{tenant_id}/conversations/{conversation_id}/messages
POST /tenants/{tenant_id}/conversations/{conversation_id}/sync/{peer_id}
```

This keeps the raw messaging layer protected.

The example sync endpoint returns **207 Multi-Status** when the relay rejected
one or more outbound messages. The response includes `rejected_message_ids` and
the number of inbound messages merged locally; it does not mean every message
was delivered. Keep rejected messages for retry and check the relay mailbox's
capacity and operational logs before retrying.

---

# 4. AI Tutorial

This section teaches you how to add AI in a safe and controlled way.

## 4.1 Minimal AI setup

The AI subsystem is optional and should be enabled only when needed.

```python
from xyberos.kernel import XyberosKernel, PolicyEngine
from xyberos.providers.ai import OpenAICompatibleProvider
from xyberos.subsystems.ai import AISubsystem

provider = OpenAICompatibleProvider()
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
                    },
                }
            }
        }
    }
)

class DemoPolicy(PolicyEngine):
    async def authorize(self, context, capability, resource=None):
        return True

kernel.register_provider("ai", provider)
kernel.register_subsystem("ai", AISubsystem(provider))
kernel.container.register_utility(PolicyEngine, DemoPolicy())
```

### Important note

This is a local demo pattern only. Real apps should use a trusted policy engine and validated request context.

---

## 4.2 Beginner AI usage pattern

Use a model provider only through the guarded AI subsystem.

```python
from xyberos.kernel import ExecutionContext, ExecutionContextAccessor
from xyberos.subsystems.ai import ModelMessage, ModelProvider

context = ExecutionContext("request-a", "tenant-a", "actor-a")
token = ExecutionContextAccessor.set(context)

try:
    provider = kernel.container.resolve(ModelProvider)
    result = await provider.generate([
        ModelMessage(role="user", content="Write a short welcome message")
    ])
    print(result.content)
finally:
    ExecutionContextAccessor.reset(token)
```

### Why this is safe

The guarded provider checks:

- trusted execution context exists
- actor and tenant are valid
- policy approves the `ai.generate` capability

This prevents the model from being used without app authorization.

---

## 4.3 Intermediate AI: intent resolution

Xyberos can also resolve intent from model output.

```python
from xyberos.subsystems.ai import IntentSubsystem

intent_subsystem = IntentSubsystem()
await intent_subsystem.initialize(
    {"allowed_intents": ["search", "help"]},
    kernel.container,
)
```

The model output must match the allowed intent format. Invalid or unknown intents are rejected.

### Example valid intent

```json
{
  "name": "search",
  "parameters": {
    "query": "weather in Tokyo"
  },
  "confidence": 0.86
}
```

### Key rule

AI output is still untrusted input. It cannot directly authorize actions.
Your application must validate the result and then enforce policy through the normal capability boundary.

---

## 4.4 Advanced AI app pattern

The example app in this repo includes the safe pattern: model generation behind a trusted policy boundary and tenant-scoped execution context.

Look at:

- [apps/example_crud_app/app.py](apps/example_crud_app/app.py)

It shows how to build a route that sends a prompt to the model provider only after the request has been authorized and the execution context is trusted.

---

# 5. Best Practices

Here are the most important rules when using Xyberos.

## 5.1 Keep the kernel small

Do not put everything in the kernel.

Good:

- runtime lifecycle
- execution context
- capability registry
- subsystem/provider wiring

Avoid:

- app-specific business logic
- custom web frameworks inside the kernel
- broad public API surface for every helper class

## 5.2 Use trusted execution context

Always require an application-owned identity resolver before routes execute.

## 5.3 Keep tenant boundaries strict

In your database queries and P2P access, always filter by tenant.

## 5.4 Do not expose raw capabilities

- Do not expose raw `OfflineMessagingService` directly
- Do not expose raw model provider directly
- Use guarded wrappers and application policies

## 5.5 Start small

Start with:

1. one database model
2. one authenticated tenant
3. one route
4. one policy check
5. then add AI or P2P later

---

# 6. Quick Start Cheat Sheet

## Traditional app

```python
from xyberos.kernel import XyberosKernel
from xyberos.providers.database import SQLiteProvider
from xyberos.subsystems.database import DatabaseSubsystem

provider = SQLiteProvider()
kernel = XyberosKernel({
    "xyberos": {"subsystems": {"database": {"enabled": True, "provider": "sqlite", "config": {"path": "./data/app.db"}}}}
})
kernel.register_subsystem("database", DatabaseSubsystem(provider))
await kernel.bootstrap()
```

## P2P app

```python
from xyberos.subsystems.p2p import TenantScopedMessagingService

secure = TenantScopedMessagingService(
    messaging,
    tenant_peer_map={"tenant-a": ("device-b",)},
    allowed_conversations={"tenant-a": ("conversation-1",)},
)
```

## AI app

```python
from xyberos.subsystems.ai import ModelMessage

result = await provider.generate([
    ModelMessage(role="user", content="Give me a summary")
])
```

---

# 7. Next steps

After you understand the basics, try these:

- build a simple CRUD app with login and tenant filtering
- add a P2P message boundary for a single team or tenant
- add a guarded AI route with policy approval
- read the implementation plan in [docs/implementation.md](docs/implementation.md)

The main idea is simple:

- Kernel manages runtime and lifecycle
- Subsystems expose capabilities
- Providers implement the real work
- Application code stays secure by validating tenant, actor, and resource boundaries

If you follow these rules, you will build apps that are easier to reason about and much safer than raw access to providers.
