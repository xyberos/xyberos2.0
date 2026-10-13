"""The journal: a separate SQLite file, its schema version, and its migrations.

The journal never shares a file — or a provider instance — with application data. Its schema is
owned here, applied forward-only, and refused rather than guessed when the file was written by a
newer package: an older binary must not "interpret" rows it does not understand.

Schema statements are plain SQL rather than generated migrations because the journal is one
single-host file with a version row, and because the durable extra must not depend on a migration
engine to open itself. A future schema version appends a step to ``_MIGRATIONS``; existing files are
upgraded in one transaction, in order, and the version row is what proves it happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from sqlalchemy import text

    from xyberos.database.sqlite import SqliteDatabase, SqliteSettings
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("durable", error) from error

from xyberos.durable.contracts import utc_now
from xyberos.errors import DurableConfigurationError, DurableSchemaError

JOURNAL_SCHEMA_VERSION = 1


def to_iso(moment: datetime) -> str:
    """Render a timestamp as a sortable, timezone-aware UTC string."""
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def from_iso(value: str) -> datetime:
    """Parse a timestamp written by :func:`to_iso`."""
    return datetime.fromisoformat(value)


_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS journal_metadata (
        name TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS workflow_definitions (
        workflow TEXT NOT NULL,
        version TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        metadata TEXT NOT NULL,
        registered_at TEXT NOT NULL,
        PRIMARY KEY (workflow, version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS executions (
        execution_id TEXT PRIMARY KEY,
        workflow TEXT NOT NULL,
        version TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        status TEXT NOT NULL,
        input TEXT NOT NULL,
        result TEXT,
        failure_kind TEXT,
        failure_message TEXT,
        current_step TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        submitted_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        deadline_at TEXT,
        cancellation_requested_at TEXT,
        cancellation_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_steps (
        execution_id TEXT NOT NULL,
        step_id TEXT NOT NULL,
        state TEXT NOT NULL,
        state_detail TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        output TEXT,
        error_type TEXT,
        error_message TEXT,
        started_at TEXT,
        finished_at TEXT,
        idempotency_key TEXT,
        PRIMARY KEY (execution_id, step_id),
        FOREIGN KEY (execution_id) REFERENCES executions (execution_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS execution_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT,
        execution_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        step_id TEXT,
        attempt INTEGER,
        detail TEXT,
        at TEXT NOT NULL,
        FOREIGN KEY (execution_id) REFERENCES executions (execution_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_leases (
        execution_id TEXT PRIMARY KEY,
        owner TEXT NOT NULL,
        fence INTEGER NOT NULL,
        acquired_at TEXT NOT NULL,
        heartbeat_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        FOREIGN KEY (execution_id) REFERENCES executions (execution_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduled_retries (
        execution_id TEXT PRIMARY KEY,
        step_id TEXT NOT NULL,
        attempt INTEGER NOT NULL,
        due_at TEXT NOT NULL,
        error_type TEXT,
        reason TEXT,
        FOREIGN KEY (execution_id) REFERENCES executions (execution_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX IF NOT EXISTS executions_status_idx ON executions (status, submitted_at)",
    "CREATE INDEX IF NOT EXISTS executions_deadline_idx ON executions (deadline_at)",
    "CREATE INDEX IF NOT EXISTS execution_events_execution_idx "
    "ON execution_events (execution_id, event_id)",
    "CREATE INDEX IF NOT EXISTS worker_leases_expiry_idx ON worker_leases (expires_at)",
    "CREATE INDEX IF NOT EXISTS scheduled_retries_due_idx ON scheduled_retries (due_at)",
)

_MIGRATIONS: dict[int, tuple[str, ...]] = {1: _SCHEMA}


@dataclass(frozen=True)
class JournalSettings:
    """Explicit, configurable defaults for one journal file.

    ``synchronous="FULL"`` is the default here, unlike the application database: the journal exists
    to survive a crash, so the durability of a committed transition matters more than write speed.
    A journal must be a file, because an in-memory journal loses exactly what durability is for.
    """

    path: str | Path = "var/journal.db"
    lease_ttl_seconds: float = 30.0
    max_payload_bytes: int = 64 * 1024
    synchronous: str = "FULL"
    busy_timeout_ms: int = 5000
    retry_attempts: int = 5
    retry_base_delay: float = 0.05
    read_only: bool = False
    """Open the journal for inspection only: no migration, no writing, no file creation.

    A journal written by a newer package is still refused, because reading rows this package would
    misinterpret is the failure the version check exists to prevent — but the refusal is the only
    thing that can happen, so `xyberos durable status` cannot bring a journal forward by looking at
    it.
    """

    def __post_init__(self) -> None:
        location = str(self.path).strip()
        if location == ":memory:" or location.startswith("file::memory:"):
            raise DurableConfigurationError(
                "the durable journal cannot be in memory: its purpose is to survive the process"
            )
        if self.lease_ttl_seconds <= 0:
            raise DurableConfigurationError("lease_ttl_seconds must be greater than zero")
        if self.max_payload_bytes <= 0:
            raise DurableConfigurationError("max_payload_bytes must be greater than zero")

    def sqlite_settings(self) -> SqliteSettings:
        """Return the SQLite settings this journal runs with.

        The journal is a separate file from the application database, so both can use WAL without
        competing for the same write lock.
        """
        return SqliteSettings(
            path=self.path,
            journal_mode="WAL",
            synchronous=self.synchronous,
            busy_timeout_ms=self.busy_timeout_ms,
            retry_attempts=self.retry_attempts,
            retry_base_delay=self.retry_base_delay,
            read_only=self.read_only,
        )


class Journal:
    """Owns the journal file, its schema, and its version."""

    def __init__(self, settings: JournalSettings | None = None) -> None:
        self.settings = JournalSettings() if settings is None else settings
        self._database = SqliteDatabase(self.settings.sqlite_settings())

    @property
    def database(self) -> SqliteDatabase:
        """The SQLite database the journal's statements run on."""
        return self._database

    @property
    def path(self) -> Path | None:
        """The journal file."""
        return self._database.settings.file_path

    async def start(self) -> None:
        """Start the database and bring the schema to this package's version.

        A read-only journal is *checked* rather than migrated, and the check is the same refusal: a
        newer file may hold rows this package would misread, and "open it anyway" is how a durable
        executor corrupts history.
        """
        await self._database.start()
        try:
            if self.settings.read_only:
                self._refuse_newer(await self.version())
            else:
                await self.migrate()
        except DurableSchemaError:
            await self._database.aclose()
            raise

    async def aclose(self) -> None:
        """Release the engine."""
        await self._database.aclose()

    async def migrate(self) -> int:
        """Apply pending schema steps, or refuse a journal written by a newer package.

        Refusing is the point: a newer file may contain rows this package would silently
        misinterpret, and "open it anyway" is how a durable executor corrupts history.
        """
        recorded = await self.version()
        self._refuse_newer(recorded)
        if recorded == JOURNAL_SCHEMA_VERSION:
            return recorded
        async with self._database.transaction() as connection:
            for version in range((recorded or 0) + 1, JOURNAL_SCHEMA_VERSION + 1):
                for statement in _MIGRATIONS[version]:
                    await connection.execute(text(statement))
                await connection.execute(
                    text(
                        "INSERT INTO journal_metadata (name, value) VALUES ('schema_version', :v)"
                        " ON CONFLICT (name) DO UPDATE SET value = excluded.value"
                    ),
                    {"v": str(version)},
                )
            await connection.execute(
                text(
                    "INSERT INTO journal_metadata (name, value) VALUES ('created_at', :now)"
                    " ON CONFLICT (name) DO NOTHING"
                ),
                {"now": to_iso(utc_now())},
            )
        return JOURNAL_SCHEMA_VERSION

    async def version(self) -> int | None:
        """Return the schema version recorded in the file, or ``None`` for an empty journal."""
        async with self._database.transaction() as connection:
            exists = await connection.execute(
                text(
                    "SELECT name FROM sqlite_master WHERE type = 'table' "
                    "AND name = 'journal_metadata'"
                )
            )
            if exists.first() is None:
                return None
            row = (
                await connection.execute(
                    text("SELECT value FROM journal_metadata WHERE name = 'schema_version'")
                )
            ).first()
        return None if row is None else int(row[0])

    def _refuse_newer(self, recorded: int | None) -> None:
        """Raise when the file was written by a package newer than this one."""
        if recorded is not None and recorded > JOURNAL_SCHEMA_VERSION:
            raise DurableSchemaError(
                f"the journal uses schema version {recorded}, but this package understands "
                f"version {JOURNAL_SCHEMA_VERSION}: upgrade xyberos or point at another journal"
            )


async def open_journal(settings: JournalSettings | None = None) -> Journal:
    """Create, start, migrate, and return a journal the caller owns and closes."""
    from xyberos.durable import warn_experimental

    warn_experimental("xyberos.durable")
    journal = Journal(settings)
    await journal.start()
    return journal
