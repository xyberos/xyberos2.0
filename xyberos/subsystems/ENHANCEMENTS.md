# Xyberos 2.0: Developer-Friendly API Design

My main recommendation is to design Xyberos around the code developers want to write, rather than the internal architecture they need to understand.

A developer should be able to build a conventional application in a few lines, add a database without infrastructure setup, and introduce AI or explicit flows only when needed. The kernel should handle lifecycle, registration, and execution internally by default, while allowing advanced developers to configure those details when necessary.

## 1. The ideal developer experience

I would establish four principles:

* Simple by default: sensible defaults for SQLite, configuration, lifecycle, and error handling.

* Explicit when needed: developers can define authorization, providers, execution flows, and policies directly.

* Progressive complexity: adding AI or a subsystem should not require rewriting an existing application.

* Python-native: familiar decorators, `async` functions, type hints, and dependency injection where useful.

The same application should be able to grow through these stages:

1. Traditional application

Routes · Services · SQLite

2. Modular application

Providers · Plugins · Authentication · Events

3. AI-enabled application

AI facade · Memory · Knowledge · Tool calling

4. Explicit orchestration

Flow · Conditional execution · Retries · Tracing

Each stage should add capabilities to the same application, not introduce a separate programming model.

## 2. Example 1 — Build a basic web application

The first impression matters most. A developer should not have to understand the kernel, registry, provider lifecycle, or capability system just to expose an endpoint.

I recommend an API like this:

Python

Run

```
# app.py
from xyberos import App

app = App()

@app.get("/")
async def home(request):
    return {"message": "Hello from Xyberos"}

@app.get("/health")
async def health(request):
    return {"status": "ok"}
```

Start it with a familiar command:

Bash

```
xyberos dev app:app
```

The framework should automatically initialize the runtime, use sensible defaults, and shut down cleanly.

These examples propose a target public API. They are not claims that all shown methods already exist in the current repository.

Design requirement: `App()` should be a thin facade over the existing Starlette integration and Xyberos runtime, not a second application framework.

## 3. Example 2 — SQLite without configuration overhead

SQLite should be the default because developers can start building immediately.

Python

Run

```
# app.py
from xyberos import App
from xyberos.db import Model, field

app = App()  # SQLite by default


class Product(Model):
    name: str = field()
    price: float = field()


@app.post("/products")
async def create_product(request):
    data = await request.json()

    product = await Product.create(
        name=data["name"],
        price=data["price"],
    )

    return product


@app.get("/products/{product_id}")
async def get_product(request):
    product_id = int(request.path_params["product_id"])
    return await Product.get(product_id)
```

This is an illustrative ORM-style API, not a verified implementation.

The actual design should provide:

* Automatic SQLite database initialization.

* Explicit schema migrations.

* Consistent async database operations.

* Parameterized queries and safe input validation.

* Transactions and rollback.

* A clean path to PostgreSQL without rewriting business logic wherever practical.

I would not build a complete ORM immediately unless Xyberos genuinely needs one. Initially, a small repository interface or a well-supported existing ORM may be more practical.

For example, a repository pattern could look like this:

Python

Run

```
class ProductService:
    def __init__(self, database):
        self.database = database

    async def get_product(self, product_id: int):
        return await self.database.fetch_one(
            "SELECT id, name, price FROM products WHERE id = ?",
            (product_id,),
        )
```

The public database API should remain consistent even if the underlying provider changes.

## 4. Example 3 — Keep business logic outside routes

Avoid turning route handlers into the place where all business logic lives.

Recommended structure:

```
myapp/
├── app.py
├── config.py
├── models/
│   └── product.py
├── services/
│   └── product_service.py
├── routes/
│   └── products.py
└── tests/
    └── test_products.py
```

Example service:

Python

Run

```
# services/product_service.py

class ProductService:
    def __init__(self, repository):
        self.repository = repository

    async def create_product(self, name: str, price: float):
        if not name.strip():
            raise ValueError("Product name is required")

        if price < 0:
            raise ValueError("Price cannot be negative")

        return await self.repository.create(
            name=name.strip(),
            price=price,
        )
```

Example route:

Python

Run

```
# routes/products.py

from xyberos import Router

router = Router()

@router.post("/")
async def create_product(request, products):
    data = await request.json()

    product = await products.create_product(
        name=data["name"],
        price=data["price"],
    )

    return product
```

Here, `products` represents an injected `ProductService`. Xyberos should document one consistent dependency-injection mechanism rather than requiring developers to look up services manually from a global registry.

For example, the target design could support typed injection:

Python

Run

```
async def create_product(
    request,
    products: ProductService,
):
    ...
```

The runtime would resolve the service and its dependencies. This is a proposed convention, and the actual implementation should use a mechanism compatible with Starlette's request and endpoint model.

Important: application-level validation is not a replacement for authorization. Tenant ownership and permissions must be checked before returning or modifying a resource.

## 5. Example 4 — Plugins that do not require framework expertise

Plugins should be simple to discover, install, enable, configure, and remove.

A developer should be able to enable a plugin without learning how the kernel registry works internally.

Python

Run

```
from xyberos import App

app = App()

app.use("database")
app.use("auth")
app.use("email")
```

A plugin that needs configuration could use:

Python

Run

```
app.use(
    "email",
    provider="smtp",
    host="localhost",
    port=1025,
)
```

The plugin API should standardize:

* Initialization and shutdown.

* Configuration validation.

* Dependency declarations.

* Service registration.

* Health checks.

* Error reporting.

* Optional capabilities and permissions.

### Suggested plugin conventions

| Developer action      | Expected behavior                |
| --------------------- | -------------------------------- |
| Enable a plugin       | Register and initialize it       |
| Missing dependency    | Report an actionable error       |
| Invalid configuration | Fail early with a clear message  |
| Disable a plugin      | Remove its functionality cleanly |
| Plugin startup fails  | Roll back partial initialization |
| App shuts down        | Close plugin-owned resources     |

I would also separate built-in subsystems from third-party plugins conceptually, even if they share the same extension contract.

For example, the database subsystem is foundational infrastructure, while a third-party payment integration is an optional extension. They should not necessarily receive identical default permissions.

## 6. Example 5 — AI should be simple to add

This is where Xyberos can distinguish itself from conventional web frameworks.

A developer should not need to learn the kernel, memory subsystem, model-provider registry, tool registry, and Flow engine just to make one model call.

I recommend a default AI facade.

Python

Run

```
from xyberos import App

app = App()

ai = app.ai()

@app.post("/ask")
async def ask(request):
    data = await request.json()

    answer = await ai.ask(data["question"])

    return {"answer": answer}
```

The default facade should handle provider selection, configuration, timeouts, and error normalization. Developers should be able to configure a model explicitly when needed.

For example:

Python

Run

```
ai = app.ai(
    provider="openai",
    model="your-configured-model",
)
```

Credentials should come from environment variables or a secrets provider, not hardcoded source code.

The AI facade should have a deliberately small initial API:

| Method          | Purpose                                   |
| --------------- | ----------------------------------------- |
| `ai.ask()`      | Get a text response                       |
| `ai.generate()` | Generate structured or constrained output |
| `ai.embed()`    | Create embeddings                         |
| `ai.stream()`   | Stream a response                         |
| `ai.tool()`     | Register an approved tool                 |

These are proposed API names. They should be finalized after examining the existing implementation and deciding which underlying model abstractions to reuse.

### Add knowledge only when needed

A retrieval-augmented generation application could look like this:

Python

Run

```
from xyberos import App

app = App()

knowledge = app.knowledge(
    source="./documents",
)

ai = app.ai()

@app.post("/support")
async def support(request):
    data = await request.json()

    documents = await knowledge.search(
        data["question"],
        limit=5,
    )

    answer = await ai.ask(
        question=data["question"],
        context=documents,
    )

    return {"answer": answer}
```

This illustrates the desired developer experience, not a complete production RAG implementation.

For a document-grounded assistant, Xyberos should also provide configurable controls for source citations, relevance thresholds, access restrictions, and abstaining when evidence is insufficient. Passing retrieved documents to a model does not, by itself, guarantee that the model will answer only from those documents.

## 7. Example 6 — Flow should be explicit, not mandatory

The Flow subsystem should be easy to use when an application genuinely needs orchestration.

Consider an AI support request that must retrieve knowledge, generate a draft, and validate the answer.

The developer-facing API could look like this:

Python

Run

```
from xyberos import App, Flow

app = App()

support_flow = (
    Flow("support")
    .step("retrieve", retrieve_documents)
    .step("answer", generate_answer)
    .step("validate", validate_answer)
)

app.flow(support_flow)
```

The flow is illustrative; the current repository's actual builder API should take precedence when implementing it.

Execution might look like:

Python

Run

```
result = await app.run_flow(
    "support",
    input={"question": question},
)
```

The engine should offer a small set of predictable controls:

* Sequential steps.

* Conditional branches.

* Per-step timeouts.

* Bounded retries.

* Cancellation.

* Structured execution traces.

* Explicit input and output contracts.

Do not require Flow for a simple operation such as:

Python

Run

```
product = await products.get_product(product_id)
```

Nor should developers have to wrap every AI call in a flow.

### Keep two levels of control

Simple mode

Python

Run

```
answer = await app.ai().ask(question)
```

For ordinary AI tasks.

Explicit mode

Python

Run

```
result = await app.run_flow(
    "support",
    input={"question": question},
)
```

For multi-step operations requiring explicit control and observability.

The kernel should own execution boundaries and lifecycle. Flow should own orchestration. Application services should own business rules. Keeping those responsibilities separate is more important than the exact syntax.

## 8. Example 7 — Configuration that is easy to understand

Developers should be able to inspect one configuration file and understand how their application behaves.

A proposed `xyberos.toml`:

TOML

```
[app]
name = "myapp"
debug = true

[database]
provider = "sqlite"
url = "sqlite:///./app.db"

[server]
host = "127.0.0.1"
port = 8000

[ai]
enabled = false

[flow]
enabled = false
```

The defaults should work without a configuration file. Configuration should be explicit when a developer needs to change behavior.

Recommended rules:

1. Environment variables override file configuration.

2. Secrets are never written to generated configuration files.

3. Invalid settings produce actionable errors.

4. Optional subsystems are not initialized unless enabled or used.

5. Configuration is validated before the application starts accepting requests.

Avoid exposing dozens of low-level settings before there are real use cases for them.

## 9. Example 8 — Testing should be equally simple

A developer-friendly platform must make tests easy to write without launching unnecessary infrastructure.

A target API could look like this:

Python

Run

```
# tests/test_products.py

from xyberos.testing import TestClient
from app import app


async def test_health():
    async with TestClient(app) as client:
        response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

The testing tools should support:

* An isolated temporary SQLite database.

* Dependency overrides.

* Mock AI providers.

* Mock external services.

* Startup and shutdown testing.

* Flow execution inspection.

* Authentication and authorization testing.

* Deterministic tests without real model API calls.

These are proposed testing conventions. The final API should follow the actual test infrastructure used by Xyberos.

One especially useful feature would be a built-in way to replace a registered provider during tests without modifying production configuration.

## 10. Improve the CLI and project scaffolding

Developer experience begins before the first line of application code.

I recommend a CLI with a small, consistent set of commands:

| Command               | Purpose                                      |
| --------------------- | -------------------------------------------- |
| `xyberos new myapp`   | Create a starter project                     |
| `xyberos dev app:app` | Start development server                     |
| `xyberos run app:app` | Run the application                          |
| `xyberos test`        | Execute tests                                |
| `xyberos db migrate`  | Apply migrations                             |
| `xyberos doctor`      | Diagnose configuration and dependency issues |
| `xyberos plugins`     | Inspect available plugins                    |

These commands are proposed, not a claim that they currently exist.

The generated project should be minimal:

```
myapp/
├── app.py
├── pyproject.toml
├── xyberos.toml
└── tests/
    └── test_app.py
```

Only generate additional directories when the developer requests them. A template that creates ten empty subsystems, multiple configuration files, and a large dependency graph would undermine the goal of simplicity.

A useful `xyberos doctor` command should check Python compatibility, configuration validity, database connectivity, plugin initialization, and common dependency problems.

## 11. Make the internal architecture invisible until needed

This is my strongest recommendation for the public API.

The current architecture contains legitimate concepts such as kernels, registries, providers, subsystems, capabilities, and flows. However, most application developers should not have to work with all of them directly.

I would divide the public API into three levels:

Level 1 — Application API

Default

`App`, `Router`, database access, services, configuration, and testing.

Intended for most developers.

Level 2 — Capability API

`app.use()`, `app.ai()`, `app.knowledge()`, `app.flow()`, and provider selection.

Intended for developers adding optional functionality.

Level 3 — Kernel API

Explicit lifecycle management, registry access, execution context, policies, and custom subsystem registration.

Intended for platform developers and advanced integrations.

The levels should share the same underlying runtime and security rules. The simpler interfaces should not silently bypass authorization or weaken execution guarantees.

## 12. Which features should you implement first?

I would prioritize the following public API surface rather than adding more subsystems immediately.

| Priority | Feature                              | Reason                                        |
| -------- | ------------------------------------ | --------------------------------------------- |
| P0       | `App()` and lifecycle management     | Establishes the basic developer experience    |
| P0       | Routing and error handling           | Makes conventional apps practical             |
| P0       | SQLite provider and migrations       | Enables zero-server local development         |
| P0       | Dependency injection and services    | Keeps business logic maintainable             |
| P0       | Testing utilities                    | Makes applications verifiable                 |
| P1       | Configuration and CLI                | Improves onboarding and daily workflow        |
| P1       | Plugin and provider interfaces       | Enables extensibility                         |
| P1       | Simple AI facade                     | Introduces AI without mandatory orchestration |
| P2       | Flow builder and tracing             | Supports explicit multi-step execution        |
| P2       | Memory and knowledge adapters        | Adds retrieval and persistence capabilities   |
| P3       | Durable workflow integration and P2P | Expands into more specialized requirements    |

The priorities are recommendations, not a claim about current implementation status.

## 13. The benchmark I would use before releasing Xyberos 2.0

Build the same small application using Xyberos and FastAPI:

* Three CRUD endpoints.

* SQLite persistence.

* Input validation.

* Authentication.

* Tenant-aware authorization.

* Automated tests.

* A documented local development command.

Then build a second version with an AI endpoint and a three-step flow.

Compare setup time, application code, dependency count, testability, error messages, performance, and the effort needed to add a new provider.

The goal should not simply be fewer lines of code. It should be less application complexity without sacrificing control, reliability, or maintainability.

## Final recommendation

For Xyberos 2.0, I would standardize the developer experience around a few primary concepts:

Python

Run

```
from xyberos import App

app = App()                        # Application and runtime
app.use("auth")                    # Optional capabilities
app.db                             # Database interface
app.ai()                           # AI facade
app.knowledge(...)                 # Retrieval
app.flow(...)                      # Explicit orchestration
```

This is a proposed public API direction; the final names and signatures should be reconciled with the current codebase before implementation.

Keep the kernel, registries, provider lifecycle, and security enforcement underneath these interfaces. Expose them directly for developers who need advanced control, but do not make them prerequisites for building ordinary applications.

The primary design objective should be that a developer can build a useful non-AI application in minutes, then add AI or complex flows incrementally without changing the application's fundamental structure.
