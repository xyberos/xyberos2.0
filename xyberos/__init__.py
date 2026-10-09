"""Public package surface for Xyberos 2.0.

This module defines the package-level API contract used by application code and
keeps the import surface intentionally small and stable. The root package exposes
core runtime modules lazily so optional subsystems remain importable without
forcing a full runtime configuration at import time.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("xyberos-minimal")
except PackageNotFoundError:
    __version__ = "2.0.0"

__all__ = ["__version__", "kernel", "http", "providers", "subsystems"]


def __getattr__(name: str):
    if name in {"kernel", "http", "providers", "subsystems"}:
        return import_module(f"xyberos.{name}")
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
