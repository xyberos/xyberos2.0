"""Resolving the ``module:attribute`` targets given on the command line.

``check`` and ``run`` both need to name something in the caller's project. The format is the one an
ASGI server already uses, deliberately: a developer should not have to learn a second convention to
point a command at the same object.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from xyberos._extras import suggest_extra
from xyberos.cli.errors import CliError

__all__ = ["load_target", "parse_target"]


def parse_target(spec: str) -> tuple[str, str | None]:
    """Split ``module:attribute`` into its two halves.

    The attribute is optional, because the ASGI server this wraps also accepts a bare module and
    looks for a conventional attribute in it. A trailing ``:`` is rejected rather than treated as
    "no attribute", since it is almost always a truncated target.
    """
    module, separator, attribute = spec.partition(":")
    if not module:
        raise CliError(f"the target {spec!r} names no module", exit_code=2)
    if separator and not attribute:
        raise CliError(f"the target {spec!r} ends with ':' but names no attribute", exit_code=2)
    return module, attribute or None


def load_target(spec: str, *, app_dir: Path | None = None) -> Any:
    """Import ``module:attribute`` and return it, or explain which half failed.

    ``app_dir`` is the same escape hatch the ASGI server offers: a ``src`` layout is importable only
    once the project is installed, and this makes it importable without installing it.

    A missing dependency inside the target is reported with the extra that provides it rather than
    being replaced by "cannot import": the package name and the extra are the two facts a reader
    needs, and losing either one turns a fix into a search.
    """
    if app_dir is not None:
        _add_to_path(app_dir)
    module_name, attribute = parse_target(spec)
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as error:
        missing = (error.name or "").split(".", 1)[0]
        if missing and missing != module_name and not module_name.startswith(f"{missing}."):
            raise CliError(
                f"cannot import {module_name!r}: {error}.{_extra_hint(error)}",
                exit_code=2,
            ) from error
        raise CliError(
            f"cannot import {module_name!r}: {error}. Run the command from your project root, "
            "install the package that provides it, or pass --app-dir with the directory above it.",
            exit_code=2,
        ) from error
    if attribute is None:
        return module
    try:
        return getattr(module, attribute)
    except AttributeError as error:
        raise CliError(
            f"{module_name!r} has no attribute {attribute!r}; it defines: "
            f"{', '.join(_public_names(module)) or '(nothing public)'}",
            exit_code=2,
        ) from error


def _public_names(module: ModuleType) -> list[str]:
    """List what a module defines itself, excluding the names it imported.

    Defaulting ``__module__`` to the module's own name keeps constants, which have none, while
    excluding imported classes and functions — a caller who mistypes an attribute wants to see the
    module's own surface, not its imports.
    """
    return sorted(
        name
        for name, value in vars(module).items()
        if not name.startswith("_")
        and not isinstance(value, ModuleType)
        and getattr(value, "__module__", module.__name__) == module.__name__
    )


def _extra_hint(error: ModuleNotFoundError) -> str:
    """Return a sentence naming the extra that provides a missing package, or nothing.

    Empty rather than a hedge when no extra is known: the sentence is appended to a message that
    already carries the original error, and an unhelpful half-sentence is noise.
    """
    extra = suggest_extra(error)
    if extra is None:
        return ""
    return f' The {extra!r} extra provides it: python -m pip install "xyberos[{extra}]".'


def _add_to_path(directory: Path) -> None:
    """Put ``directory`` first on ``sys.path``, once.

    Prepending rather than appending matters: the point is to prefer the project being inspected
    over an installed copy of the same name. The check for an existing entry keeps a repeated call
    from growing the path, which also keeps the effect visible in a test.
    """
    if not directory.is_dir():
        raise CliError(f"{directory} is not a directory", exit_code=2)
    entry = str(directory.resolve())
    if entry not in sys.path:
        sys.path.insert(0, entry)
