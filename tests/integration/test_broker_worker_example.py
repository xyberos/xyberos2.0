"""The broker recipe holds: a redelivered item reuses its execution, not its effects."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

import pytest
from broker_worker.app import (
    EFFECTS,
    InMemoryBroker,
    build_workflow,
    drain,
)

from xyberos.durable import JournalSettings, JournalStore, open_journal
from xyberos.errors import DurableConflictError


@pytest.fixture(autouse=True)
def clean_effects() -> None:
    """Effects are recorded in module state so a reader can see them; a test must reset them."""
    EFFECTS.clear()


def test_three_items_are_delivered_once_each() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = await open_journal(JournalSettings(path=Path(directory) / "journal.db"))
            try:
                store = JournalStore(journal)
                broker = InMemoryBroker()
                workflow = build_workflow()
                for index in range(3):
                    broker.publish(f"order-{index}", f"order-{index}")

                results = await drain(broker, store, workflow)

                assert results == [
                    "order-0: completed",
                    "order-1: completed",
                    "order-2: completed",
                ]
                assert len(await store.list_executions()) == 3
            finally:
                await journal.aclose()

    asyncio.run(scenario())


def test_a_redelivered_item_does_not_repeat_its_effects() -> None:
    """The whole reason the execution id is the delivery id."""

    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = await open_journal(JournalSettings(path=Path(directory) / "journal.db"))
            try:
                store = JournalStore(journal)
                broker = InMemoryBroker()
                workflow = build_workflow()
                delivery = broker.publish("order-0", "order-0")

                await drain(broker, store, workflow)
                after_first_pass = list(EFFECTS["order-0"])
                broker.redeliver(delivery)

                results = await drain(broker, store, workflow)

                assert results == ["order-0: completed"]
                assert EFFECTS["order-0"] == after_first_pass
                assert len(EFFECTS["order-0"]) == 2  # one charge, one notification
                assert len(await store.list_executions()) == 1
            finally:
                await journal.aclose()

    asyncio.run(scenario())


def test_an_acknowledged_item_stops_arriving() -> None:
    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = await open_journal(JournalSettings(path=Path(directory) / "journal.db"))
            try:
                store = JournalStore(journal)
                broker = InMemoryBroker()
                workflow = build_workflow()
                delivery = broker.publish("order-0", "order-0")

                await drain(broker, store, workflow)
                broker.redeliver(delivery)
                await drain(broker, store, workflow)

                assert broker.receive() == []
                assert delivery.deliveries == 3  # one delivery, one redelivery, one empty poll
            finally:
                await journal.aclose()

    asyncio.run(scenario())


def test_the_same_execution_id_for_different_work_is_refused() -> None:
    """Idempotence is scoped to the *same* work, so a bug cannot silently overwrite an execution."""

    async def scenario() -> None:
        with tempfile.TemporaryDirectory() as directory:
            journal = await open_journal(JournalSettings(path=Path(directory) / "journal.db"))
            try:
                store = JournalStore(journal)
                workflow = build_workflow()
                await store.submit(workflow, input="order-0", execution_id="order-0")

                changed = build_workflow().step  # a different object is still the same definition
                assert callable(changed)

                with pytest.raises(DurableConflictError):
                    await store.submit(
                        workflow,
                        input="different work entirely",
                        execution_id="order-0",
                        submission_key="a-different-submission",
                    )
            finally:
                await journal.aclose()

    asyncio.run(scenario())
