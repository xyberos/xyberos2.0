"""The ``migrate`` command: call the migration runner the database extra already exposes.

Alembic remains the engine and the direction stays explicit — migrations are applied at deploy time
by a command someone ran, never implicitly at application startup. This command exists so that the
deploy step is one documented line instead of a hand-written script.

A database URL carries a password, and a password must never reach terminal scrollback or a CI log.
So nothing here prints the URL as given: the summary quotes a redacted form, and a failure becomes
one of this command's own messages with every form of the secret scrubbed out. That is deliberate
rather than defensive — a traceback is an ordinary way for configuration to end up in a log, and the
underlying failure may quote the value it was given.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING
from urllib.parse import unquote

from xyberos.cli.errors import CliError

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["migrate"]

DEFAULT_DIRECTORY = "migrations"

REDACTED = "***"


def migrate(directory: Path, *, url: str, use_asyncio: bool = False) -> str:
    """Apply the revisions in ``directory`` to ``url`` and return a one-line summary.

    The URL is the **synchronous** one for the default path, because Alembic's engine is
    synchronous. ``use_asyncio`` is for a caller that is already inside an event loop.
    """
    from xyberos.database import apply_migrations, run_migrations

    if not directory.is_dir():
        raise CliError(f"no migration directory at {directory}", exit_code=2)
    try:
        if use_asyncio:
            asyncio.run(apply_migrations(directory, url=url))
        else:
            run_migrations(directory, url=url)
    except Exception as error:
        # A CLI boundary reports; it does not re-raise. Anything escaping here would print a
        # traceback, and a traceback quotes the value that caused the failure.
        raise CliError(f"migrations failed for {redact(url)}: {scrub(str(error), url)}") from error
    return f"migrations: applied {directory} to {redact(url)}"


def redact(url: str) -> str:
    """Render a database URL without the password it carries."""
    password = _password(url)
    if not password:
        return url
    return url.replace(password, REDACTED, 1)


def scrub(message: str, url: str) -> str:
    """Return ``message`` with the URL it mentions, and every form of its password, removed.

    Both encodings are replaced, because a password may be reported as it was given or as a driver
    decoded it, and covering only one would leave the other in the log. The whole URL is replaced as
    well: a message that quotes it quotes the password inside it. The longest form goes first, so a
    decoded password that is a prefix of its encoded form cannot defeat the longer replacement.
    """
    scrubbed = message.replace(url, redact(url))
    for secret in _secrets(url):
        scrubbed = scrubbed.replace(secret, REDACTED)
    return scrubbed


def _password(url: str) -> str:
    """Return the password in ``url``, or an empty string when it carries none."""
    _scheme, separator, remainder = url.partition("://")
    if not separator or "@" not in remainder:
        return ""
    credentials, _, _location = remainder.rpartition("@")
    _user, separator, password = credentials.partition(":")
    return password if separator else ""


def _secrets(url: str) -> tuple[str, ...]:
    """Return the password forms that must not appear in output, longest first."""
    password = _password(url)
    if not password:
        return ()
    candidates = {password, unquote(password)}
    return tuple(sorted((value for value in candidates if value), key=len, reverse=True))
