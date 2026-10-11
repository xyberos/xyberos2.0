"""The files ``xyberos new`` writes.

Keeping the template here rather than in a data directory means the scaffold is part of the type
checked package, and a test can assert that what it writes is a project that imports and passes its
own test. Nothing in the template depends on a Xyberos internal: every import it makes is a
documented public path.
"""

from __future__ import annotations

from pathlib import Path

from xyberos.cli.errors import CliError

__all__ = ["files_for", "validate_name"]

# The version is deliberately not imported from xyberos: a generated project pins a range, and the
# installed version is the one that matters, not the one that happened to scaffold it.
PYPROJECT = """\
[build-system]
requires = ["hatchling>=1.25,<2"]
build-backend = "hatchling.build"

[project]
name = "{name}"
version = "0.1.0"
description = "{name}, built on Xyberos"
requires-python = ">=3.10"
dependencies = [
  # Xyberos is not published yet. Install your checkout into this environment first:
  #   python -m pip install -e /path/to/xyberos3[http]
  "xyberos",
]

[project.optional-dependencies]
http = ["xyberos[http]"]
dev = ["pytest>=8,<10"]

[tool.hatch.build.targets.wheel]
packages = ["src/{name}"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
"""

GITIGNORE = """\
__pycache__/
*.py[cod]
.venv/
var/
*.db
*.db-wal
*.db-shm
"""

CONFIG = """\
[app]
name = "{name}"
environment = "development"
"""

PACKAGE_INIT = '''\
"""{name}: an application built on Xyberos."""
'''

APP = '''\
"""Compose the application and expose it as an ASGI application.

Start from here: `create_app` is the composition root, and a route handler declares what it needs
instead of looking it up. See the getting started guide for what each piece is for.
"""

from __future__ import annotations

from typing import Annotated

from starlette.applications import Starlette

from xyberos import App, Inject, Settings
from xyberos.http import HttpAdapter


class Greeter:
    """A service with no HTTP types in it, so it can be tested on its own."""

    def __init__(self, app_name: str) -> None:
        self._app_name = app_name

    def greet(self, name: str) -> str:
        """Return the greeting line for ``name``."""
        return f"{self._app_name} says hello, {name}"


def create_app(settings: Settings | None = None) -> App:
    """Compose the application."""
    resolved = settings if settings is not None else Settings.load()
    app = App(settings=resolved)
    app.provide(Greeter, instance=Greeter(resolved.app.name))

    @app.get("/")
    async def greet(greeter: Annotated[Greeter, Inject()]) -> dict[str, str]:
        return {"greeting": greeter.greet("world")}

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Report that the application started and is accepting requests."""
        return {"status": "ok"}

    return app


def build_asgi_app(app: App) -> Starlette:
    """Build the ASGI application that the runtime runs inside."""
    return HttpAdapter(app).asgi_app


asgi_app = build_asgi_app(create_app())
'''

TEST = '''\
"""The application answers, and the wiring is the application's own."""

from {name}.app import create_app

from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client


def test_health_reports_ready() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        assert client.get("/health").json() == {{"status": "ok"}}


def test_the_greeting_uses_the_configured_name() -> None:
    with create_test_client(HttpAdapter(create_app())) as client:
        assert "says hello" in client.get("/").json()["greeting"]
'''

README = """\
# {name}

An application built on Xyberos.

## Run it

```powershell
python -m pip install -e ".[http,dev]" uvicorn
pytest
xyberos check --app {name}.app:create_app --app-dir src
xyberos run --app {name}.app:asgi_app --app-dir src --reload
```

`xyberos migrate` applies Alembic revisions when this application grows a database; see the
database operations guide. Deploy behind an ASGI server that terminates TLS, and set
`environment = "production"` in the configuration.
"""


def validate_name(name: str) -> str:
    """Return ``name`` if it can be a distribution and import name, or explain why not."""
    if not name.isidentifier():
        raise CliError(
            f"{name!r} is not a valid Python identifier, so it cannot be a package name",
            exit_code=2,
        )
    if not name.islower():
        raise CliError(
            f"{name!r} must be lower case: the distribution and import names are the same "
            "here, and an import name that differs from its directory is a source of confusion",
            exit_code=2,
        )
    return name


def files_for(name: str) -> dict[Path, str]:
    """Return the files to write, keyed by path relative to the new project directory."""
    validated = validate_name(name)
    return {
        Path("pyproject.toml"): PYPROJECT.format(name=validated),
        Path(".gitignore"): GITIGNORE,
        Path("xyberos.toml"): CONFIG.format(name=validated),
        Path("README.md"): README.format(name=validated),
        Path("src") / validated / "__init__.py": PACKAGE_INIT.format(name=validated),
        Path("src") / validated / "app.py": APP,
        Path("tests") / "test_app.py": TEST.format(name=validated),
    }
