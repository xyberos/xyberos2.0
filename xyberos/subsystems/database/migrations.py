from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from .contracts import Database


@dataclass(frozen=True)
class SchemaMigration:
    version: int
    statements: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.version, int)
            or isinstance(self.version, bool)
            or self.version < 1
        ):
            raise ValueError("Migration version must be a positive integer.")
        if not isinstance(self.statements, tuple) or not self.statements:
            raise ValueError("A migration must contain at least one SQL statement.")
        if any(not isinstance(statement, str) or not statement.strip() for statement in self.statements):
            raise ValueError("Migration statements must be non-empty SQL text.")


class SchemaMigrator:
    """Apply an ordered, forward-only sequence of transactional SQL migrations."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def apply(self, migrations: Sequence[SchemaMigration]) -> tuple[int, ...]:
        ordered = tuple(migrations)
        if not all(isinstance(migration, SchemaMigration) for migration in ordered):
            raise TypeError("Migrations must contain SchemaMigration values.")
        versions = tuple(migration.version for migration in ordered)
        if versions != tuple(sorted(set(versions))):
            raise ValueError("Migrations must have unique, strictly increasing versions.")

        await self._database.execute(
            """
            CREATE TABLE IF NOT EXISTS xyberos_schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        known_versions = set(versions)
        applied_rows = await self._database.fetch_all(
            "SELECT version FROM xyberos_schema_migrations ORDER BY version"
        )
        applied_versions = {row["version"] for row in applied_rows}
        unknown = applied_versions - known_versions
        if unknown:
            raise RuntimeError(
                "Database contains schema migration versions unknown to this release: "
                + ", ".join(str(version) for version in sorted(unknown))
            )

        applied_now: list[int] = []
        for migration in ordered:
            async with self._database.transaction() as transaction:
                already_applied = await transaction.fetch_one(
                    "SELECT version FROM xyberos_schema_migrations WHERE version = ?",
                    (migration.version,),
                )
                if already_applied is not None:
                    continue
                for statement in migration.statements:
                    await transaction.execute(statement)
                await transaction.execute(
                    "INSERT INTO xyberos_schema_migrations (version, applied_at) "
                    "VALUES (?, ?)",
                    (migration.version, datetime.now(timezone.utc).isoformat()),
                )
            applied_now.append(migration.version)
        return tuple(applied_now)
