# Xyberos

Xyberos is an experimental, composable Python application runtime. Its planned stable
surface is application composition, typed dependencies, Starlette-backed HTTP, SQLite,
and explicit in-process Flow execution. Durable execution and AI adapters are optional.

The project is currently at version `0.0.0`. Phases 0–3 are complete: the architecture baseline,
the application runtime, the Starlette HTTP adapter with the SQLite database provider, and the
trusted plugin/capability model. Flow, AI adapters, and durable execution are still in progress.
Breaking changes are expected before `1.0.0`.

## Runtime

The stable `xyberos` import root exposes the core runtime: application composition, typed
configuration, dependency injection, lifecycle, context/logging helpers, and route records. It
never imports optional capabilities.

```python
from typing import Annotated

from xyberos import App, Inject, Settings


class Repository:
    async def list_users(self) -> list[str]:
        return []


class UserService:
    def __init__(self, repository: Annotated[Repository, Inject()]) -> None:
        self.repository = repository


async def main() -> None:
    app = App(settings=Settings.load())
    app.provide(Repository)
    app.provide(UserService)

    async with app.lifespan():
        service = await app.resolve(UserService)
        print(await service.list_users())
```

See [the runtime guide](docs/runtime.md) for scopes, lifecycle, configuration, and the error
taxonomy.

## HTTP and database

HTTP support is an optional extra over Starlette, and the SQLite provider is an optional extra
over SQLAlchemy Core and `aiosqlite`:

```python
from typing import Annotated

from xyberos import App, Inject
from xyberos.database import DatabaseProvider, SqliteSettings, sqlite_provider
from xyberos.http import HttpAdapter

app = App()
app.provide(DatabaseProvider, factory=sqlite_provider(SqliteSettings()), eager=True)


@app.get("/health")
async def health(database: Annotated[DatabaseProvider, Inject()]) -> dict[str, str]:
    await database.health()
    return {"status": "ready"}


asgi_app = HttpAdapter(app).asgi_app
```

See the [HTTP guide](docs/http.md), the [database operations guide](docs/database.md), and the
[`sqlite_crud` example](examples/sqlite_crud/README.md).

## Plugins

Trusted, in-process capability integrations are added explicitly:

```python
from xyberos import App, Plugin


class GreetingPlugin(Plugin[None]):
    name = "greeting"
    config_type = None

    def register(self, app: App, config: None) -> None:
        app.provide(Greeter, instance=Greeter())


app = App()
app.add_plugin(GreetingPlugin())
```

Plugins are ordinary Python code — there is no sandbox — and `app.diagnostics().render()` reports
where every provider came from and in which order plugins start. See the
[plugin guide](docs/plugins.md) and the [`custom_plugin` example](examples/custom_plugin/README.md).

## Development

Use Python 3.10 or newer. Install the project with development tools and run the quality
suite:

```powershell
python -m pip install -e ".[dev,http,database]"
python -m pytest
ruff check src tests examples
ruff format --check src tests examples
mypy
python -m build
```

Optional capability dependencies are intentionally separate:

```powershell
python -m pip install -e ".[http]"
python -m pip install -e ".[database]"
python -m pip install -e ".[ollama]"
python -m pip install -e ".[durable]"
```

See [the architecture plan](docs/PLAN.md), [the phase-by-phase implementation plan](docs/implementation.md), [the runtime guide](docs/runtime.md), [the HTTP guide](docs/http.md), [the database operations guide](docs/database.md), [the plugin guide](docs/plugins.md), and [the architecture decisions](docs/adr/).

## Status and compatibility

`0.x` releases are preview releases. The first release intended to provide the stable
runtime and Flow guarantees described in the implementation plan will be `1.0.0`.
The project license is intentionally undecided; do not redistribute it until a license is
selected.
