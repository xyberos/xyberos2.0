"""The ``migrate`` command: call the migration runner the database extra already exposes.

Alembic remains the engine and the direction stays explicit — migrations are applied at deploy time
by a command someone ran, never implicitly at application startup. This command exists so that the
deploy step is one documented line instead of a hand-written script.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from xyberos.cli.errors import CliError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["migrate"]

DEFAULT_DIRECTORY = "migrations"


def migrate(directory: Path, *, url: str, use_asyncio: bool = False) -> str:
    """Apply the revisions in ``directory`` to ``url`` and return a one-line summary.

    The URL is the **synchronous** one for the default path, because Alembic's engine is
    synchronous. ``use_asyncio`` is for a caller that is already inside an event loop.
    """
    from xyberos.database import apply_migrations, run_migrations

    if not directory.is_dir():
        raise CliError(f"no migration directory at {directory}", exit_code=2)
    if use_asyncio:
        asyncio.run(apply_migrations(directory, url=url))
    else:
        run_migrations(directory, url=url)
    return f"migrations: applied {directory} to {_redact(url)}"


def _redact(url: str) -> str:
    """Render a database URL without any password it carries.

    A URL is configuration, and configuration ends up in terminal scrollback and CI logs.
    """
    scheme, separator, remainder = url.partition("://")
    if not separator or "@" not in remainder:
        return url
    credentials, _, location = remainder.rpartition("@")
    user, _, _password = credentials.partition(":")
    return f"{scheme}://{user}:***@{location}"
