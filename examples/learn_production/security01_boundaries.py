"""Walkthrough — the boundaries that hold, and the one that is explicitly yours to hold.

Run it with:

    python -m learn_production.security01_boundaries
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path
from typing import ClassVar

from xyberos import PLUGIN_API_VERSION, App, Plugin, Settings
from xyberos.errors import XyberosError
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

#: The packages an adapter brings in, and therefore the ones core must not import on its own.
ADAPTER_PACKAGES = ("sqlalchemy", "aiosqlite", "alembic", "starlette", "httpx")


class Audit(Plugin[None]):
    """A plugin that registers nothing, so only its metadata is under test."""

    name: ClassVar[str] = "audit"
    api_version: ClassVar[str] = "2"

    def register(self, app: App, config: None) -> None:
        """Register nothing; a plugin for a future API never gets this far."""


class Leaking(Exception):
    """An error that carries a secret and is not safe to expose."""

    def __init__(self) -> None:
        super().__init__("upstream refused the token sk-live-0123456789")


class Records(logging.Handler):
    """An in-memory handler, so the transcript can be the records themselves."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep the record instead of writing it anywhere."""
        self.records.append(record)


def report(label: str, action: object) -> None:
    """Print the failure a boundary produces, without the value that triggered it."""
    try:
        action()  # type: ignore[operator]
    except XyberosError as error:
        # One message names the file it could not find, absolutely. Normalising the working
        # directory keeps this transcript about the boundary rather than about this machine.
        message = str(error).replace(str(Path.cwd()), "<cwd>").replace("\\", "/")
        print(f"{label}: {type(error).__name__}: {message}")


def imported_adapter_packages() -> list[str]:
    """Return the adapter packages present after importing the framework, measured fresh."""
    script = (
        "import sys\n"
        "import xyberos\n"
        f"names = {ADAPTER_PACKAGES!r}\n"
        "print(', '.join(sorted(name for name in names if name in sys.modules)) or 'none')\n"
    )
    completed = subprocess.run(  # noqa: S603  # a fixed script, no shell, no untrusted input
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip().split(", ")


async def leaky_route() -> dict[str, object]:
    """Raise an error whose message must never reach the client."""
    raise Leaking


async def scenario() -> None:
    """Measure each boundary: configuration, imports, plugin compatibility, and error bodies."""
    # 1. Configuration reports the *setting*, never the value it refused.
    report(
        "a value that is the wrong type",
        lambda: Settings.load(environ={"XYBEROS_APP__DEBUG": "definitely"}),
    )
    report(
        "a setting the runtime does not know",
        lambda: Settings.load(environ={"XYBEROS_APP__SIGNING_KEY": "sk-live-0123456789"}),
    )
    report(
        "a configuration file that is not there",
        lambda: Settings.load(config_path="nowhere.toml"),
    )
    # 2. Importing the framework does not import an adapter. The extras are opt-in at the level of
    # `sys.modules`, which is what keeps an unused driver out of the deployment's dependency tree.
    print("import xyberos pulls in:", ", ".join(imported_adapter_packages()))
    print("and the plugin API this runtime supports:", PLUGIN_API_VERSION)

    # 3. A plugin written for a different plugin API is refused by name, before it can register.
    report("a plugin for another API", lambda: App().add_plugin(Audit()))

    # 4. An error that is not an HttpError is replaced in the response, and its message goes only to
    # the log. The client learns that the request failed; the operator learns why.
    captured = logging.getLogger("xyberos.http")
    handler = Records()
    captured.addHandler(handler)
    previous = captured.level
    captured.setLevel(logging.INFO)
    try:
        app = App()
        app.get("/leak")(leaky_route)
        with create_test_client(HttpAdapter(app)) as client:
            response = client.get("/leak")
        print("response body:", response.json())
        print(
            "and the log, which the operator sees:",
            [
                (record.getMessage(), str(record.exc_info[1]))
                for record in handler.records
                if record.exc_info
            ],
        )
    finally:
        captured.removeHandler(handler)
        captured.setLevel(previous)


def main() -> None:
    """Run the scenario."""
    asyncio.run(scenario())


if __name__ == "__main__":
    main()
