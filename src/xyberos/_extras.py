"""Turn a failed optional import into an actionable error.

Every module that imports a dependency belonging to an extra wraps that import, so installing the
missing pieces is a copy-and-paste answer instead of a bare ``ModuleNotFoundError`` naming a
package the user never asked for by name. Core imports nothing from here.
"""

from __future__ import annotations


def extra_error(extra: str, error: ModuleNotFoundError) -> ModuleNotFoundError:
    """Return the error to raise when an extra's own dependency cannot be imported.

    ``extra`` is the name under ``xyberos[...]`` that provides the failed import, so the original
    message is carried along for diagnosis while the fix is stated as a command.
    """
    return ModuleNotFoundError(
        f"the {extra!r} extra cannot be imported: install it with "
        f"'pip install \"xyberos[{extra}]\"' ({error})"
    )
