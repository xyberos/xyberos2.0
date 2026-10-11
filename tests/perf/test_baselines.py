"""Resource baselines: startup, route latency, workflow overhead, contention, journal throughput.

Run this module on its own when you want the numbers, because a passing test's output is captured:

    python -m pytest -s tests/perf

Every assertion here is a ceiling roughly an order of magnitude above the recorded baseline. A tight
threshold on a shared machine fails for reasons that have nothing to do with the change under test,
so the point is to notice a change of *kind* — construction that became quadratic, a connection
opened per request, a journal write per event — and then look at it. The recorded baseline, with the
machine it was taken on, is in `docs/performance.md`, so a reader can tell a regression from a
different machine.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from perf.harness import Report, time_async, time_call
from xyberos import App, Workflow
from xyberos.database import temporary_database
from xyberos.durable import ActivityPolicy, JournalSettings, JournalStore, open_journal
from xyberos.durable.worker import DurableWorker, WorkerSettings
from xyberos.execution import WorkflowExecutor
from xyberos.http import HttpAdapter
from xyberos.http.testing import create_test_client

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

# Ceilings, not targets: each is about an order of magnitude above the recorded baseline.
STARTUP_CEILING_SECONDS = 2.0
REQUEST_CEILING_SECONDS = 0.25
WORKFLOW_STEP_CEILING_SECONDS = 0.05
JOURNAL_EXECUTION_CEILING_SECONDS = 0.5
CONTENTION_CEILING_SECONDS = 20.0

PROVIDERS = 50
REQUESTS = 100
WORKFLOW_STEPS = 20
JOURNAL_EXECUTIONS = 20
CONCURRENT_WRITERS = 20
WRITES = 50


@pytest.fixture(scope="module")
def report() -> Iterator[Report]:
    """One table per run, printed when the module finishes rather than five times."""
    collected = Report()
    yield collected
    print("\n" + collected.render())


def test_composing_and_validating_many_providers(report: Report) -> None:
    contracts = [type(f"Service{index}", (), {}) for index in range(PROVIDERS)]

    def scenario() -> None:
        app = App()
        for contract in contracts:
            app.provide(contract)
        app.validate()

    measurement = time_call(report, f"compose + validate {PROVIDERS} providers", scenario, repeat=5)

    assert measurement.median_ms / 1000 < STARTUP_CEILING_SECONDS


def test_starting_and_stopping_many_eager_providers(report: Report) -> None:
    contracts = [type(f"Eager{index}", (), {}) for index in range(PROVIDERS)]

    async def scenario() -> None:
        app = App()
        for contract in contracts:
            app.provide(contract, eager=True)
        async with app.lifespan():
            pass

    async def run() -> None:
        measurement = await time_async(
            report, f"start + stop {PROVIDERS} eager providers", scenario, repeat=5
        )

        assert measurement.median_ms / 1000 < STARTUP_CEILING_SECONDS

    asyncio.run(run())


def test_route_latency_through_the_test_client(report: Report) -> None:
    async def ping() -> dict[str, str]:
        return {"status": "ok"}

    app = App()
    app.get("/ping")(ping)

    with create_test_client(HttpAdapter(app)) as client:
        measurement = time_call(
            report,
            f"route round trip, in process ({REQUESTS}x)",
            lambda: client.get("/ping"),
            repeat=REQUESTS,
        )

    assert measurement.median_ms / 1000 < REQUEST_CEILING_SECONDS


def test_workflow_overhead_per_step(report: Report) -> None:
    async def step(value: Any, context: Any) -> str:
        return "step"

    async def run() -> None:
        workflow = Workflow("baseline")
        for index in range(WORKFLOW_STEPS):
            workflow = workflow.step(f"step{index}", step)

        async def scenario() -> None:
            await workflow.run(executor=WorkflowExecutor())

        measurement = await time_async(
            report, f"workflow of {WORKFLOW_STEPS} steps", scenario, repeat=5
        )
        per_step = measurement.median_ms / WORKFLOW_STEPS / 1000
        report.add("  per step within that workflow", [per_step])

        assert per_step < WORKFLOW_STEP_CEILING_SECONDS

    asyncio.run(run())


def test_sqlite_contention_under_the_retry_policy(report: Report) -> None:
    """Concurrent writers all finish; the bounded retry policy is what makes that true."""

    async def run() -> None:
        async with temporary_database() as database:
            async with database.transaction() as connection:
                await connection.execute(
                    text("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
                )

            async def write(index: int) -> None:
                async def operation(connection: Any) -> None:
                    await connection.execute(
                        text("INSERT INTO items (name) VALUES (:name)"),
                        {"name": f"item-{index}"},
                    )

                await database.retrying(operation, attempts=10, base_delay=0.01)

            started = time.perf_counter()
            await asyncio.gather(*(write(index) for index in range(CONCURRENT_WRITERS)))
            elapsed = time.perf_counter() - started
            report.add(f"sqlite: {CONCURRENT_WRITERS} concurrent writers", [elapsed])

            async with database.transaction() as connection:
                written = (
                    await connection.execute(text("SELECT COUNT(*) FROM items"))
                ).scalar_one()

        assert int(written) == CONCURRENT_WRITERS
        assert elapsed < CONTENTION_CEILING_SECONDS

    asyncio.run(run())


def test_sqlite_write_throughput(report: Report, tmp_path: Path) -> None:
    """Writes are serialised, so this is the number that decides whether SQLite is enough.

    One connection, one transaction per write, no contention: this is the *best* a single writer
    does, which makes it the ceiling a busy deployment approaches rather than a figure to be
    optimistic about. The reciprocal of the median is the implied write rate.
    """

    async def run() -> None:
        async with temporary_database(directory=tmp_path) as database:
            async with database.transaction() as connection:
                await connection.execute(
                    text("CREATE TABLE writes (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
                )

            samples: list[float] = []
            for index in range(WRITES):
                started = time.perf_counter()
                async with database.transaction() as connection:
                    await connection.execute(
                        text("INSERT INTO writes (name) VALUES (:name)"),
                        {"name": f"write-{index}"},
                    )
                samples.append(time.perf_counter() - started)
            report.add(f"sqlite: one write per transaction ({WRITES}x)", samples)

            async with database.transaction() as connection:
                written = (
                    await connection.execute(text("SELECT COUNT(*) FROM writes"))
                ).scalar_one()

        assert int(written) == WRITES

    asyncio.run(run())


def test_durable_journal_throughput(report: Report, tmp_path: Path) -> None:
    """Every step is at least one journal commit, so this number is dominated by durability."""

    async def step(value: Any, context: Any) -> str:
        return "done"

    async def run() -> None:
        journal = await open_journal(JournalSettings(path=tmp_path / "journal.db"))
        try:
            store = JournalStore(journal)
            workflow = Workflow("baseline", version="1").step("run", step)
            for index in range(JOURNAL_EXECUTIONS):
                await store.submit(workflow, input={"index": index})

            worker = DurableWorker(
                store,
                {"baseline:1": workflow},
                activities={"run": ActivityPolicy(idempotent=True)},
                settings=WorkerSettings(owner="perf"),
            )

            started = time.perf_counter()
            while await worker.run_once() is not None:
                pass
            elapsed = time.perf_counter() - started
            per_execution = elapsed / JOURNAL_EXECUTIONS
            report.add(f"journal: {JOURNAL_EXECUTIONS} executions submitted + run", [per_execution])

            assert per_execution < JOURNAL_EXECUTION_CEILING_SECONDS
        finally:
            await journal.aclose()

    asyncio.run(run())
