# Getting started

> Status: Phase 7. This guide takes you from an empty directory to a running application. It uses
> only stable core APIs and the optional `http` extra. For what "stable" means here, see the
> [stability guide](./stability.md).

Xyberos is not published to PyPI yet, so install it from a checkout of this repository. Python 3.10
or newer is required.

```powershell
git clone <repository> xyberos3
cd xyberos3
python -m pip install -e ".[http]" uvicorn
```

`uvicorn` is not a Xyberos dependency. Xyberos does not implement an ASGI server, so any ASGI server
can run the application you build here.

## The smallest application

An application is a composition root: you name the services it has and the routes it answers, and
the runtime owns their lifetimes.

```python
import asyncio
from typing import Annotated

from xyberos import App, Inject


class Greeter:
    def greet(self, name: str) -> str:
        return f"hello, {name}"


async def main() -> None:
    app = App()
    app.provide(Greeter)

    async with app.lifespan():
        greeter = await app.resolve(Greeter)
        print(greeter.greet("world"))


asyncio.run(main())
```

Three things are worth noticing, because everything else follows from them:

- **Nothing was configured by name.** `Greeter` is registered by its own class, and a service that
  needs it declares `Annotated[Greeter, Inject()]`. There is no container to look things up in and
  no parameter-name magic.
- **The lifecycle is explicit.** `app.lifespan()` runs `validate`, `start`, and `stop`. Nothing is
  constructed eagerly unless you ask for it, and everything the application owns is closed at the
  end of the block.
- **`import xyberos` imports no optional dependency.** The HTTP, database, AI-adapter, and durable
  packages are separate, so a program that does not use them cannot break because of them.

## Add HTTP

```python
from typing import Annotated

from starlette.applications import Starlette
from starlette.requests import Request

from xyberos import App, Inject, Settings
from xyberos.http import HttpAdapter


class Greeter:
    def greet(self, name: str) -> str:
        return f"hello, {name}"


def create_app() -> App:
    app = App(settings=Settings.load())
    app.provide(Greeter)

    @app.get("/")
    async def greet(request: Request, greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"greeting": greeter.greet(request.query_params.get("name", "world"))}

    return app


def build_asgi_app(app: App) -> Starlette:
    return HttpAdapter(app).asgi_app


asgi_app = build_asgi_app(create_app())
```

```powershell
uvicorn --app-dir . app:asgi_app
curl "http://127.0.0.1:8000/?name=reader"
```

The handler's parameters are the whole interface: `request: Request` comes from Starlette, and
anything marked `Inject()` comes from the graph, resolved inside the request scope. Both are
validated when `HttpAdapter(...)` is constructed, so a handler with a typo or a missing provider
fails at startup rather than on the first request. See the [HTTP guide](./http.md).

A complete, runnable version of this is [the hello app example](../examples/hello_app/README.md),
including a settings file and an integration test that exercises it.

## Configure it

Settings come from `xyberos.toml`:

```toml
[app]
name = "hello_app"
environment = "development"
```

Precedence, highest first: explicit arguments, `XYBEROS_` environment variables, the configuration
file, then defaults. Nesting uses a double underscore, so `XYBEROS_APP__NAME=other` overrides the
file, and `XYBEROS_CONFIG=/etc/xyberos.toml` replaces the file that is searched for.

Read settings through the application, not by importing a global: `app.settings.app.name`,
`app.settings.app.environment`, `app.settings.app.debug`, and
`app.settings.app.shutdown_timeout`. An unknown key, an incompatible type, or an unsupported
`schema_version` is rejected with a field-level `ConfigurationError` that names the field — settings
are validated before the application starts, never during a request.

Optional capabilities own their own sections, `[plugins.<name>]` and `[ai.<name>]`, with the same
precedence. Core keeps their contents opaque; the capability validates its own keys. See the
[plugin guide](./plugins.md) and the [AI guide](./ai.md).

## Choose lifetimes

| Scope | One instance per | Use it for |
| --- | --- | --- |
| `Scope.APP` (default) | application | connection pools, clients, configuration-backed services |
| `Scope.REQUEST` | request | per-request state, a unit of work, anything holding a request value |
| `Scope.TRANSIENT` | resolution | stateless helpers; may not own a managed resource |

`app.provide(Greeter)` registers an app-scoped service and lets the runtime construct it. Pass
`factory=` or `instance=` when construction needs arguments, and `eager=True` when the service must
be proven to start before the application accepts work:

```python
app.provide(Greeter, instance=Greeter("hello_app"), eager=True)
```

A longer-lived service may not depend on a shorter-lived one, and validation says so with the
resolution path. The [runtime guide](./runtime.md) covers the rules in full.

## Grow the application

| You want | Read | Install |
| --- | --- | --- |
| HTTP routes, middleware, error responses | [HTTP guide](./http.md) | `.[http]` |
| SQLite with migrations and transaction retries | [database operations guide](./database.md) | `.[database]` |
| Contribution points, typed plugin configuration | [plugin guide](./plugins.md) | core |
| Retries, timeouts, branching multi-step work | [workflow guide](./workflow.md) | core |
| A provider-neutral model facade and tools | [AI guide](./ai.md) | core, `.[ollama]` for Ollama |
| Surviving a process death mid-workflow | [durable execution guide](./durable.md) | `.[durable]` |
| Writing tests without live infrastructure | [testing guide](./testing.md) | `.[http]` for the test client |
| What broke and why | [troubleshooting guide](./troubleshooting.md) | — |

A conventional layout keeps the optional extras at the edges:

```text
myapp/
├── xyberos.toml         # configuration
├── migrations/          # Alembic revisions, run at deploy time
└── src/myapp/
    ├── app.py           # create_app(): composition and routes only
    ├── service.py       # business rules; no HTTP types
    └── tables.py        # SQLAlchemy Core tables
```

Routes and composition belong in one module, business rules in another, and neither needs the other
to be testable: a service is a plain class, which is why the test suites in this repository can
check behavior without a server. [The SQLite CRUD example](../examples/sqlite_crud/README.md) is
this layout, filled in.

## Next steps

- Read the [runtime guide](./runtime.md) for providers, scopes, lifecycle, and configuration.
- Read the [testing guide](./testing.md) before you write your first test; the deterministic doubles
  are what make a clock-dependent or model-dependent test fast.
- Set `environment = "production"` and `debug = false` in your deployment configuration, and read
  the [security guide](./security.md) before you expose the application to a network.
