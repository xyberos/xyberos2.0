"""Inspect a durable journal without changing it: `xyberos durable status`.

The durable executor is experimental and its journal is a SQLite file an operator could already read
by hand — which is the problem this command removes. Two rules make it safe to point at a production
journal: the file is opened through SQLite's ``mode=ro`` URI, so a write is refused by the driver
rather than by the code above it, and the schema is never migrated, so a journal written by a newer
package is reported as the refusal `xyberos.durable` already raises instead of being brought forward
by looking at it. SQLite still creates its own WAL index (``-shm``) and an empty ``-wal`` beside a
database it opens; those are its bookkeeping, and the journal's bytes are unchanged. The command
reads; a worker or a person decides.

Everything it reports comes from `xyberos.durable`'s own readers — `JournalStats` for the counters,
`JournalStore.oldest_non_terminal` for the longest wait, `list_executions` for the parked attempts —
so the report cannot disagree with the API an application calls. It exits ``0`` whenever the journal
is readable: a status is a report, and a pipeline that needs a verdict reads the JSON.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from xyberos.cli.errors import CliError

if TYPE_CHECKING:
    from xyberos.durable import ExecutionView, Journal, JournalStats

__all__ = ["PARKED_LIMIT", "STATUS_DOCUMENT_VERSION", "document", "status"]

STATUS_DOCUMENT_VERSION = 1
"""The version of the ``durable status --json`` document. ADR 0020 records why it is a contract."""

PARKED_LIMIT = 20
"""How many parked executions the report lists. The total always comes from the journal."""

# Split so the report shows the queue and the outcomes on separate, comparable lines.
_ACTIVE_FIELDS = ("queued", "running", "retrying", "waiting")
_FINISHED_FIELDS = ("completed", "failed", "cancelled", "timed_out")
_COUNT_FIELDS = _ACTIVE_FIELDS + _FINISHED_FIELDS


@dataclass(frozen=True)
class _Execution:
    """One execution, flattened to the facts a report shows rather than the whole view."""

    execution_id: str
    workflow: str
    version: str
    status: str
    submitted_at: datetime
    current_step: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class _Snapshot:
    """Everything `durable status` reports, read in one pass while the journal is open."""

    path: Path
    schema_version: int | None
    size_bytes: int
    counts: dict[str, int]
    expired_leases: int
    oldest_lease_age_seconds: float | None
    incompatible: int
    oldest: _Execution | None
    parked: tuple[_Execution, ...]
    parked_total: int


def status(*, journal_path: Path | None = None) -> str:
    """Return the text report: the counters, the longest wait, and why each execution is parked."""
    return _render(asyncio.run(_read(journal_path)))


def document(*, journal_path: Path | None = None) -> str:
    """Return `durable status --json`: the same snapshot as one machine-readable document."""
    return json.dumps(_document(asyncio.run(_read(journal_path))), indent=2, sort_keys=True)


async def _read(journal_path: Path | None) -> _Snapshot:
    """Open the journal read-only, read everything the report needs, and close it."""
    from xyberos.durable import ExecutionStatus, JournalSettings, JournalStore, open_journal

    default = JournalSettings().path
    settings = JournalSettings(
        path=default if journal_path is None else journal_path,
        read_only=True,
    )
    location = Path(str(settings.path)).expanduser()
    if not location.exists():
        raise CliError(
            f"no journal at {location}: point --journal at one, or let a worker create it"
        )
    journal = await open_journal(settings)
    try:
        store = JournalStore(journal)
        stats = await store.stats()
        oldest = await store.oldest_non_terminal()
        parked = await store.list_executions(status=ExecutionStatus.WAITING, limit=PARKED_LIMIT)
        return _snapshot(journal, stats, oldest, parked, await journal.version(), location)
    finally:
        await journal.aclose()


def _snapshot(
    journal: Journal,
    stats: JournalStats,
    oldest: ExecutionView | None,
    parked: tuple[ExecutionView, ...],
    schema_version: int | None,
    location: Path,
) -> _Snapshot:
    """Build the snapshot from the readers' results, touching the file only to read its size."""
    path = journal.path if journal.path is not None else location
    return _Snapshot(
        path=path,
        schema_version=schema_version,
        size_bytes=path.stat().st_size,
        counts={name: int(getattr(stats, name)) for name in _COUNT_FIELDS},
        expired_leases=stats.expired_leases,
        oldest_lease_age_seconds=stats.oldest_lease_age_seconds,
        incompatible=stats.incompatible,
        oldest=None if oldest is None else _execution(oldest),
        parked=tuple(_execution(view, reason=True) for view in parked),
        parked_total=stats.waiting,
    )


def _execution(view: ExecutionView, *, reason: bool = False) -> _Execution:
    """Flatten one execution view, optionally taking the reason from the event that parked it."""
    return _Execution(
        execution_id=view.execution_id,
        workflow=view.workflow,
        version=view.version,
        status=view.status.value,
        submitted_at=view.submitted_at,
        current_step=view.current_step,
        reason=_park_reason(view) if reason else None,
    )


def _park_reason(view: ExecutionView) -> str | None:
    """Return why the execution was parked: the detail of its most recent waiting event."""
    from xyberos.durable import EventKind

    for event in reversed(view.events):
        if event.kind is EventKind.WAITING:
            return event.detail
    return None


def _render(snapshot: _Snapshot) -> str:
    """Return the text report, one fact per line so a diff of two runs is readable."""
    schema = "none" if snapshot.schema_version is None else str(snapshot.schema_version)
    lines = [
        f"journal: {snapshot.path.as_posix()}",
        f"schema version: {schema}",
        f"size: {snapshot.size_bytes} bytes",
        _counts(_ACTIVE_FIELDS, snapshot.counts),
        _counts(_FINISHED_FIELDS, snapshot.counts),
        f"expired leases: {snapshot.expired_leases}",
        f"incompatible definitions: {snapshot.incompatible}",
        f"oldest unfinished: {_describe(snapshot.oldest)}",
        _describe_parked(snapshot),
    ]
    lines.extend(f"  - {_describe(execution)}" for execution in snapshot.parked)
    lines.append("read-only: opened mode=ro, never migrated, no journal byte written")
    return "\n".join(lines)


def _counts(fields: tuple[str, ...], counts: dict[str, int]) -> str:
    """Render a group of counters on one line."""
    return "  ".join(f"{name.replace('_', ' ')}: {counts[name]}" for name in fields)


def _describe_parked(snapshot: _Snapshot) -> str:
    shown = len(snapshot.parked)
    total = snapshot.parked_total
    if total > shown:
        return f"parked: {total} (showing {shown})"
    return f"parked: {total}"


def _describe(execution: _Execution | None) -> str:
    """Describe one execution in a sentence, or say there is nothing to describe."""
    if execution is None:
        return "none"
    where = "" if execution.current_step is None else f", at step {execution.current_step}"
    reason = "" if execution.reason is None else f": {execution.reason}"
    return (
        f"{execution.execution_id} ({execution.workflow} v{execution.version}, "
        f"{execution.status}, submitted {execution.submitted_at.isoformat()}{where}){reason}"
    )


def _document(snapshot: _Snapshot) -> dict[str, object]:
    """Return the document, with a fixed shape so a reader never has to check for a key."""
    return {
        "document": STATUS_DOCUMENT_VERSION,
        "journal": {
            "path": snapshot.path.as_posix(),
            "schema_version": snapshot.schema_version,
            "size_bytes": snapshot.size_bytes,
        },
        "counts": dict(snapshot.counts),
        "leases": {
            "expired": snapshot.expired_leases,
            "oldest_age_seconds": snapshot.oldest_lease_age_seconds,
        },
        "incompatible_definitions": snapshot.incompatible,
        "oldest_unfinished": None if snapshot.oldest is None else _entry(snapshot.oldest),
        "parked": [_entry(execution) for execution in snapshot.parked],
        "parked_total": snapshot.parked_total,
    }


def _entry(execution: _Execution) -> dict[str, object]:
    return {
        "execution_id": execution.execution_id,
        "workflow": execution.workflow,
        "version": execution.version,
        "status": execution.status,
        "submitted_at": execution.submitted_at.isoformat(),
        "current_step": execution.current_step,
        "reason": execution.reason,
    }
