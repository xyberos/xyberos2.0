"""The journal owns its schema, refuses a newer one, and never shares a file by accident."""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import text

from xyberos.durable import JOURNAL_SCHEMA_VERSION, JournalSettings, open_journal
from xyberos.errors import DurableConfigurationError, DurableSchemaError

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"


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


def test_an_unstable_entry_point_warns_once_per_process() -> None:
    """The warning is a feature, so it is pinned in a subprocess where filters cannot hide it.

    Checking it here rather than in-process keeps the assertion independent of test order: the
    warning is intentionally emitted once per process, so an in-process check would pass or fail
    depending on which test ran first.
    """
    code = (
        "import asyncio, tempfile, warnings\n"
        "from pathlib import Path\n"
        "from xyberos import Workflow\n"
        "from xyberos.durable import JournalSettings, JournalStore, open_journal\n"
        "from xyberos.durable.worker import DurableWorker\n"
        "\n"
        "async def step(value, context):\n"
        "    return 'done'\n"
        "\n"
        "async def main():\n"
        "    with tempfile.TemporaryDirectory() as temporary:\n"
        "        with warnings.catch_warnings(record=True) as caught:\n"
        "            warnings.simplefilter('always')\n"
        "            journal = await open_journal(\n"
        "                JournalSettings(path=Path(temporary) / 'journal.db')\n"
        "            )\n"
        "            store = JournalStore(journal)\n"
        "            workflow = Workflow('w', version='1').step('s', step)\n"
        "            await store.submit(workflow)\n"
        "            DurableWorker(store, {'w:1': workflow})\n"
        "            DurableWorker(store, {'w:1': workflow})\n"
        "            await journal.aclose()\n"
        "        assert len(caught) == 1, [str(w.message) for w in caught]\n"
        "        message = str(caught[0].message)\n"
        "        assert caught[0].category.__name__ == 'ExperimentalWarning', caught[0].category\n"
        "        for phrase in ('experimental', 'single-host', 'at-least-once'):\n"
        "            assert phrase in message, message\n"
        "\n"
        "asyncio.run(main())\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=SOURCE_ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stderr


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
