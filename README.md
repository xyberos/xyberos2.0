# Xyberos

Xyberos is an experimental, composable Python application runtime. Its planned stable
surface is application composition, typed dependencies, Starlette-backed HTTP, SQLite,
and explicit in-process Flow execution. Durable execution and AI adapters are optional.

The project is currently at version `0.0.0`. Phase 0 (packaging, architecture, and
API-contract baseline) and Phase 1 (application runtime, registry, lifecycle, and dependency
injection) are complete; later phases are in progress. Breaking changes are expected before
`1.0.0`.

## Runtime

The stable `xyberos` import root exposes the Phase 1 runtime: application composition, typed
configuration, dependency injection, lifecycle, and context/logging helpers. It never imports
optional capabilities.

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

## Development

Use Python 3.10 or newer. Install the project with development tools and run the quality
suite:

```powershell
python -m pip install -e ".[dev]"
python -m pytest
ruff check src tests
ruff format --check src tests
mypy
python -m build
```

Optional capability dependencies are intentionally separate:

```powershell
python -m pip install -e ".[database]"
python -m pip install -e ".[ollama]"
python -m pip install -e ".[durable]"
```

See [the architecture plan](docs/PLAN.md), [the phase-by-phase implementation plan](docs/implementation.md), [the runtime guide](docs/runtime.md), and [the architecture decisions](docs/adr/).

## Status and compatibility

`0.x` releases are preview releases. The first release intended to provide the stable
runtime and Flow guarantees described in the implementation plan will be `1.0.0`.
The project license is intentionally undecided; do not redistribute it until a license is
selected.
