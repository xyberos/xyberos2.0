"""Failures the command line reports without a traceback."""

from __future__ import annotations

__all__ = ["CliError"]


class CliError(Exception):
    """A failure with a message the caller can act on.

    The exit code distinguishes "what you asked for is wrong" (``2``, the conventional usage code)
    from "what you asked for failed" (``1``), so a script can tell a typo from a broken deployment
    without parsing the message.
    """

    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code
