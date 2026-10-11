"""Deprecation mechanics for the public surface.

A deprecated name still works; it warns, and it says when it will stop working and what to use
instead. The rules for *when* to deprecate live with the versioning policy in
[`docs/stability.md`](../../docs/stability.md); this module is the mechanism those rules use.

Deprecation and experimental warnings are deliberately separate categories.
:class:`~xyberos.errors.ExperimentalWarning` says "this may change"; a deprecation warning says
"this will stop working, and here is the replacement". Users filter them differently, so they are
different classes and different call sites.
"""

from __future__ import annotations

import functools
import warnings
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

__all__ = ["XyberosDeprecationWarning", "deprecated", "warn_deprecated"]


class XyberosDeprecationWarning(DeprecationWarning):
    """Emitted when a documented name is deprecated.

    It derives from :class:`DeprecationWarning`, so it is silent by default in ordinary use, visible
    under `python -W default`, and an error under `-W error`. That is the behaviour a user expects
    from a deprecation, and it keeps a deprecation from being noisier than the problem it announces.
    """


def _message(what: str, *, since: str, removed_in: str | None, alternative: str | None) -> str:
    parts = [f"{what} is deprecated since {since}"]
    if alternative is not None:
        parts.append(f"use {alternative} instead")
    if removed_in is None:
        parts.append("it will be removed in a future release")
    else:
        parts.append(f"it will be removed in {removed_in}")
    return "; ".join(parts)


def warn_deprecated(
    what: str,
    *,
    since: str,
    removed_in: str | None = None,
    alternative: str | None = None,
    stacklevel: int = 2,
) -> None:
    """Warn that ``what`` is deprecated, naming the replacement and the removal release.

    ``what`` reads as the subject of the sentence, so pass the name as a user writes it:
    ``warn_deprecated("xyberos.App.provide(instance=...)", since="0.2", removed_in="1.0")``.
    """
    if not what.strip():
        raise ValueError("a deprecation warning needs a subject")
    if not since.strip():
        raise ValueError("a deprecation warning needs the release that deprecated it")
    warnings.warn(
        _message(what, since=since, removed_in=removed_in, alternative=alternative),
        XyberosDeprecationWarning,
        stacklevel=stacklevel,
    )


def deprecated(
    what: str,
    *,
    since: str,
    removed_in: str | None = None,
    alternative: str | None = None,
) -> Callable[[T], T]:
    """Return a decorator that announces a deprecated callable when it is used.

    The decorator preserves the wrapped signature and docstring, so type checkers and
    `help()` still describe the real function while callers get the warning.
    """

    def decorate(target: T) -> T:
        @functools.wraps(target)  # type: ignore[arg-type]
        def wrapper(*args: object, **kwargs: object) -> object:
            warn_deprecated(
                what, since=since, removed_in=removed_in, alternative=alternative, stacklevel=2
            )
            return target(*args, **kwargs)  # type: ignore[operator]

        return wrapper  # type: ignore[return-value]

    return decorate
