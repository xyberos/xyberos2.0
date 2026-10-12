"""One clock, so every recorded time is written by the same function.

The application records times and never prints them, which is why the lessons' transcripts stay
deterministic without a stubbed clock: what a reader sees is who did what and what the body was.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """Return the current time as an ISO-8601 string in UTC.

    ``timezone.utc`` rather than ``datetime.UTC``, which is 3.11 and later: this line is checked
    against the oldest version the package supports.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
