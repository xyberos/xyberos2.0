"""`xyberos durable status` reports a journal, and cannot change the one it reports.

The two promises this file exists for are negative: the command must not write, and it must not
migrate. Both are asserted against the file rather than against the code — a byte-level snapshot
before and after, and a recorded schema version that a newer journal keeps after being refused.

The journal itself is built through `xyberos.durable`'s own API, so a change to the store's
semantics fails here rather than in an operator's terminal.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from xyberos import Workflow
from xyberos.cli.durable import document, status
from xyberos.cli.errors import CliError
from xyberos.cli.main import main
from xyberos.durable import JournalSettings, JournalStore, open_journal

SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src"

# The command is a thin wrapper, so the missing-extra path is the one thing only a subprocess can
# assert: the dependency has to be blocked before `xyberos.cli.durable` imports it.
BLOCKED_IMPORT = """
import sys

BLOCKED = {blocked!r}


class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"No module named {{name!r}}", name=name)
        return None


sys.meta_path.insert(0, Blocker())
from xyberos.cli.main import main

raise SystemExit(main(["durable", "status"]))
"""

PARK_REASON = "the step declares no retry policy"


async def step(value: object, context: object) -> str:
    return "done"


async def build_journal(path: Path) -> None:
    """Two submissions, the older of which is parked, so both reportable rows exist."""
    journal = await open_journal(JournalSettings(path=path))
    try:
        store = JournalStore(journal)
        await store.submit(Workflow("orders", version="1").step("charge", step))
        await store.submit(Workflow("reports", version="1").step("render", step))
        claim = await store.claim_next("worker-1")
        assert claim is not None, "the fixture must be able to claim work"
        await store.mark_waiting(claim, reason=PARK_REASON)
    finally:
        await journal.aclose()


@pytest.fixture
def journal_path(tmp_path: Path) -> Path:
    path = tmp_path / "journal.db"
    asyncio.run(build_journal(path))
    return path


def test_status_reports_the_counters_the_longest_wait_and_the_park_reason(
    journal_path: Path,
) -> None:
    report = status(journal_path=journal_path)

    assert f"journal: {journal_path.as_posix()}" in report
    assert "schema version: 1" in report
    assert "queued: 1  running: 0  retrying: 0  waiting: 1" in report
    assert "completed: 0  failed: 0  cancelled: 0  timed out: 0" in report
    assert "oldest unfinished: " in report
    assert PARK_REASON in report, "a parked execution is reported with the reason it was parked"
    assert "read-only:" in report


def test_the_document_carries_the_same_facts_as_the_report(journal_path: Path) -> None:
    report = status(journal_path=journal_path)
    body = json.loads(document(journal_path=journal_path))

    assert body["document"] == 1
    assert set(body) == {
        "document",
        "journal",
        "counts",
        "leases",
        "incompatible_definitions",
        "oldest_unfinished",
        "parked",
        "parked_total",
    }
    assert body["journal"]["schema_version"] == 1
    assert body["journal"]["size_bytes"] == journal_path.stat().st_size
    assert body["counts"]["queued"] == 1
    assert body["counts"]["waiting"] == 1
    assert body["parked_total"] == 1
    assert len(body["parked"]) == 1
    assert body["parked"][0]["reason"] == PARK_REASON
    assert body["parked"][0]["execution_id"] in report
    assert body["oldest_unfinished"] is not None
    assert body["oldest_unfinished"]["execution_id"] in report


def test_the_command_writes_nothing_to_the_journal_it_reads(journal_path: Path) -> None:
    """The strongest form of the promise: the journal's bytes are identical afterwards."""
    before = journal_path.read_bytes()
    listing = {item.name for item in journal_path.parent.iterdir()}

    status(journal_path=journal_path)
    document(journal_path=journal_path)

    created = {item.name for item in journal_path.parent.iterdir()} - listing

    assert journal_path.read_bytes() == before
    # SQLite creates its WAL index, and an empty WAL, when it opens a WAL database — even to read
    # one. They are its bookkeeping rather than the journal's content, and an empty WAL is the proof
    # that no page was written through them.
    assert created <= {f"{journal_path.name}-wal", f"{journal_path.name}-shm"}
    assert not (journal_path.parent / f"{journal_path.name}-wal").read_bytes()


def test_a_write_through_a_read_only_journal_is_refused(journal_path: Path) -> None:
    """Read-only is the driver's rule rather than this command's discipline: nothing can write."""

    async def attempt() -> object:
        journal = await open_journal(JournalSettings(path=journal_path, read_only=True))
        try:
            store = JournalStore(journal)
            return await store.submit(Workflow("late", version="1").step("charge", step))
        finally:
            await journal.aclose()

    before = journal_path.read_bytes()
    try:
        asyncio.run(attempt())
    except Exception as error:  # SQLite's refusal; which type carries it is not this test's subject
        assert "readonly" in str(error).lower(), str(error)
    else:
        pytest.fail("a read-only journal accepted a write")

    assert journal_path.read_bytes() == before


def test_a_journal_from_a_newer_package_is_refused_rather_than_migrated(
    journal_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _set_recorded_version(journal_path, 999)

    exit_code = main(["durable", "status", "--journal", str(journal_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "upgrade xyberos" in captured.err
    assert "DurableSchemaError" in captured.err, "the refusal is the journal's own error"
    assert _recorded_version(journal_path) == 999, "a status must not bring a journal forward"


def test_a_missing_journal_is_reported_and_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "absent.db"

    with pytest.raises(CliError) as raised:
        status(journal_path=missing)

    assert "no journal at" in str(raised.value)
    assert not missing.exists(), "a status command never creates the journal it was asked about"


def test_the_help_says_the_command_reads_only(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as listed:
        main(["durable", "--help"])

    assert listed.value.code == 0
    assert "reads only" in capsys.readouterr().out

    with pytest.raises(SystemExit) as exit_info:
        main(["durable", "status", "--help"])

    assert exit_info.value.code == 0
    assert "--journal" in capsys.readouterr().out


def test_a_core_only_install_names_the_durable_extra() -> None:
    """The command must not need the extra to say which extra it needs."""
    result = subprocess.run(
        [sys.executable, "-c", BLOCKED_IMPORT.format(blocked={"sqlalchemy"})],
        capture_output=True,
        text=True,
        cwd=SOURCE_ROOT,
        check=False,
    )

    assert result.returncode == 1, result.stdout
    assert 'pip install "xyberos[durable]"' in result.stderr, result.stderr


def _set_recorded_version(path: Path, version: int) -> None:
    """Rewrite the journal's recorded schema version, the way a newer package would have."""
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            "UPDATE journal_metadata SET value = ? WHERE name = 'schema_version'", (str(version),)
        )
        connection.commit()
    finally:
        connection.close()


def _recorded_version(path: Path) -> int:
    connection = sqlite3.connect(path)
    try:
        row = connection.execute(
            "SELECT value FROM journal_metadata WHERE name = 'schema_version'"
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return int(row[0])
