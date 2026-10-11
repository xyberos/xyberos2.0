"""The ``run`` command: hand an application to the ASGI server, and own nothing else.

The server is not a Xyberos dependency, and this command does not pretend to be one. It validates
the target format, explains how to install a server when none is present, and then gives the import
string to the server so that the server keeps ownership of reloading, workers, and shutdown. Nothing
is re-implemented here, and nothing is imported on the application's behalf — which is what keeps
``--reload`` working.
"""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import TYPE_CHECKING

from xyberos.cli.errors import CliError
from xyberos.cli.targets import parse_target

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["run"]

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

INSTALL_HINT = "python -m pip install uvicorn"


def run(
    *,
    target: str,
    factory: bool = False,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    reload: bool = False,
    app_dir: Path | None = None,
) -> None:
    """Start an ASGI server on ``target``, and return when it stops."""
    parse_target(target)
    if not 0 < port < 65536:
        raise CliError(f"port {port} is out of range", exit_code=2)
    if app_dir is not None and not app_dir.is_dir():
        raise CliError(f"{app_dir} is not a directory", exit_code=2)
    uvicorn = _import_uvicorn()
    uvicorn.run(
        target,
        factory=factory,
        host=host,
        port=port,
        reload=reload,
        app_dir=None if app_dir is None else str(app_dir),
    )


def _import_uvicorn() -> ModuleType:
    """Import the ASGI server by name, or explain how to get it.

    An ASGI server is a deployment choice, not a framework dependency, so Xyberos will not install
    one for you and will not pick one silently. The import is by name because the package is
    genuinely optional: a static import would make it a build requirement for type checking,
    which is the same mistake in a different place.
    """
    try:
        return importlib.import_module("uvicorn")
    except ModuleNotFoundError as error:
        raise CliError(
            f"no ASGI server is installed ({error}). Install one, for example: {INSTALL_HINT}"
        ) from error
