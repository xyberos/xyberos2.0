"""The ``new`` command: write a minimal project that already runs.

The scaffold is deliberately small enough to read in one sitting, and it is the same shape the
examples use — a composition root, one service, two routes, a settings file, and a test. Anything
larger would be a template someone has to delete.

An existing directory is never overwritten: a scaffolding command that can destroy work is worse
than one that refuses.
"""

from __future__ import annotations

from pathlib import Path

from xyberos.cli.errors import CliError
from xyberos.cli.scaffold import files_for

__all__ = ["new"]


def new(name: str, *, directory: Path, force: bool = False) -> list[Path]:
    """Write a new project called ``name`` under ``directory`` and return the files created."""
    files = files_for(name)
    target = directory / name
    if target.exists() and any(target.iterdir()) and not force:
        raise CliError(
            f"{target} already exists and is not empty; choose another name or remove it",
            exit_code=2,
        )
    written: list[Path] = []
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written
