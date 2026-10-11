"""Turn a failed optional import into an actionable error.

Every module that imports a dependency belonging to an extra wraps that import, so installing the
missing pieces is a copy-and-paste answer instead of a bare ``ModuleNotFoundError`` naming a
package the user never asked for by name. Core imports nothing from here.

The reverse lookup exists for the same reason in the other direction: when a *user's* module fails
to import because a third-party package is missing, the package name is the only clue to which
extra would have provided it, and saying so is the difference between a fix and a search.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

PACKAGE_EXTRAS: Mapping[str, str] = MappingProxyType(
    {
        "starlette": "http",
        "httpx": "http",
        "sqlalchemy": "database",
        "aiosqlite": "database",
        "alembic": "database",
    }
)
"""Which extra declares each optional third-party package, for error messages.

``httpx`` is declared by both ``http`` and ``ollama``; the entry names the one a reader asking the
question usually needs, and the message never claims to be exhaustive.
"""


def extra_error(extra: str, error: ModuleNotFoundError) -> ModuleNotFoundError:
    """Return the error to raise when an extra's own dependency cannot be imported.

    ``extra`` is the name under ``xyberos[...]`` that provides the failed import, so the original
    message is carried along for diagnosis while the fix is stated as a command.
    """
    return ModuleNotFoundError(
        f"the {extra!r} extra cannot be imported: install it with "
        f"'pip install \"xyberos[{extra}]\"' ({error})"
    )


def suggest_extra(error: ModuleNotFoundError) -> str | None:
    """Return the extra that provides the package ``error`` names, if one is known.

    A missing package that no extra provides returns ``None`` rather than a guess: naming the wrong
    extra is worse than naming none, because it sends the reader somewhere that cannot help.
    """
    missing = (error.name or "").split(".", 1)[0]
    return PACKAGE_EXTRAS.get(missing)
