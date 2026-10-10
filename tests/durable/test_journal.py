"""The journal owns its schema, refuses a newer one, and never shares a file by accident."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import text

from xyberos.durable import JOURNAL_SCHEMA_VERSION, JournalSettings, open_journal
from xyberos.errors import DurableConfigurationError, DurableSchemaError


def test_opening_a_journal_creates_a_versioned_file(tmp_path: Path) -> None:
    async def scenario() -> int | None:
        journal = await open_journal(JournalSettings(path=tmp_path / "journal.db"))
        try:
            return await journal.version()
        finally:
            await journal.aclose()

    assert asyncio.run(scenario()) == JOURNAL_SCHEMA_VERSION
    assert (tmp_path / "journal.db").exists()


def test_reopening_a_journal_keeps_its_version(tmp_path: Path) -> None:
    async def scenario() -> tuple[int | None, int | None]:
        settings = JournalSettings(path=tmp_path / "journal.db")
        first = await open_journal(settings)
        await first.aclose()
        second = await open_journal(settings)
        try:
            return JOURNAL_SCHEMA_VERSION, await second.version()
        finally:
            await second.aclose()

    assert asyncio.run(scenario()) == (JOURNAL_SCHEMA_VERSION, JOURNAL_SCHEMA_VERSION)


def test_a_newer_journal_is_refused_rather_than_guessed(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"

    async def scenario() -> None:
        settings = JournalSettings(path=path)
        journal = await open_journal(settings)
        async with journal.database.transaction() as connection:
            await connection.execute(
                text("UPDATE journal_metadata SET value = :version WHERE name = 'schema_version'"),
                {"version": str(JOURNAL_SCHEMA_VERSION + 1)},
            )
        await journal.aclose()
        await open_journal(settings)

    with pytest.raises(DurableSchemaError) as raised:
        asyncio.run(scenario())

    assert "upgrade xyberos" in str(raised.value)


def test_a_failed_open_releases_the_engine(tmp_path: Path) -> None:
    path = tmp_path / "journal.db"

    async def scenario() -> bool:
        settings = JournalSettings(path=path)
        journal = await open_journal(settings)
        async with journal.database.transaction() as connection:
            await connection.execute(
                text("UPDATE journal_metadata SET value = :version WHERE name = 'schema_version'"),
                {"version": str(JOURNAL_SCHEMA_VERSION + 1)},
            )
        await journal.aclose()
        with pytest.raises(DurableSchemaError):
            await open_journal(settings)
        return True

    assert asyncio.run(scenario()) is True


def test_the_journal_is_its_own_file_with_its_own_durability_defaults() -> None:
    settings = JournalSettings(path="var/journal.db")

    sqlite = settings.sqlite_settings()

    assert sqlite.path == "var/journal.db"
    assert sqlite.journal_mode == "WAL"
    assert sqlite.synchronous == "FULL"
    assert sqlite.retry_attempts >= 1


@pytest.mark.parametrize("path", [":memory:", "file::memory:?cache=shared"])
def test_an_in_memory_journal_is_refused(path: str) -> None:
    with pytest.raises(DurableConfigurationError) as raised:
        JournalSettings(path=path)

    assert "cannot be in memory" in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [("lease_ttl_seconds", 0.0), ("lease_ttl_seconds", -1.0), ("max_payload_bytes", 0)],
)
def test_journal_settings_reject_unusable_values(field: str, value: float) -> None:
    with pytest.raises(DurableConfigurationError):
        JournalSettings(**{field: value})  # type: ignore[arg-type]
