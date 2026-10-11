"""A broker-driven worker: the queue owns delivery, the journal owns progress.

Xyberos will not host durability across machines
([ADR 0015](../../docs/adr/0015-durability-is-single-host.md)), and the supported way to run at a
larger scale is to let something else deliver the work. This example is that topology, small enough
to read:

- a broker delivers an item with a **stable delivery id**;
- the item is submitted with `execution_id=delivery.id`, which makes submission idempotent for the
  same id and the same definition;
- a worker claims and runs one step at a time, committing each result before the next;
- the item is acknowledged only after the execution reaches a terminal state.

Redelivery is the whole point. An at-least-once broker *will* deliver the same item twice — after a
lost acknowledgement, after a worker dies, after a network hiccup — and because the execution id is
derived from the delivery id, the second delivery reuses the completed execution instead of charging
the customer twice.

The in-memory broker here stands in for SQS, RabbitMQ, Kafka, or whatever you already run. It is not
a durable queue, and the example does not pretend it is: everything the durability comes from lives
in the journal.
"""

from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from xyberos import StepContext, Workflow
from xyberos.durable import ActivityPolicy, JournalSettings, JournalStore, open_journal
from xyberos.durable.worker import DurableWorker, WorkerSettings

if TYPE_CHECKING:
    from collections.abc import Iterable

EFFECTS: dict[str, list[str]] = {}
"""Every external effect this example performs, keyed by delivery id, so a test can count them."""


@dataclass
class Delivery:
    """One item handed to a worker, with the id the broker will keep stable across redeliveries."""

    delivery_id: str
    payload: str
    deliveries: int = 1


@dataclass
class InMemoryBroker:
    """An at-least-once broker, in about thirty lines.

    `receive` does not remove the item: an item leaves the queue only when it is acknowledged,
    which is what makes redelivery possible at all.
    """

    queue: list[Delivery] = field(default_factory=list)
    acknowledged: set[str] = field(default_factory=set)

    def publish(self, payload: str, delivery_id: str) -> Delivery:
        """Add an item and return the delivery the worker will see."""
        delivery = Delivery(delivery_id=delivery_id, payload=payload)
        self.queue.append(delivery)
        return delivery

    def receive(self) -> list[Delivery]:
        """Return everything not yet acknowledged, counting each redelivery."""
        pending = [item for item in self.queue if item.delivery_id not in self.acknowledged]
        for item in pending:
            item.deliveries += 1
        return pending

    def acknowledge(self, delivery: Delivery) -> None:
        """Mark an item done, so it stops being redelivered."""
        self.acknowledged.add(delivery.delivery_id)

    def redeliver(self, delivery: Delivery) -> None:
        """Forget an acknowledgement, as a lost ack would, so the item arrives again."""
        self.acknowledged.discard(delivery.delivery_id)


def build_workflow() -> Workflow:
    """Two steps, the second of which must not run twice for one delivery."""

    async def charge(delivery_id: str, context: StepContext) -> str:
        EFFECTS.setdefault(delivery_id, []).append("charged")
        return delivery_id

    async def notify(delivery_id: str, context: StepContext) -> str:
        EFFECTS.setdefault(delivery_id, []).append("notified")
        return f"delivery {delivery_id} complete"

    return (
        Workflow("broker-item", version="1", input_type=str)
        .step("charge", charge)
        .step("notify", notify)
        .edge("charge", "notify")
    )


async def drain(
    broker: InMemoryBroker,
    store: JournalStore,
    workflow: Workflow,
    *,
    owner: str = "worker-1",
) -> list[str]:
    """Deliver, submit, run to completion, acknowledge — and return what each execution reported."""
    worker = DurableWorker(
        store,
        {"broker-item:1": workflow},
        activities={
            "charge": ActivityPolicy(idempotent=True),
            "notify": ActivityPolicy(idempotent=True),
        },
        settings=WorkerSettings(owner=owner),
    )
    results: list[str] = []
    for delivery in broker.receive():
        await store.submit(
            workflow,
            input=delivery.payload,
            execution_id=delivery.delivery_id,
            submission_key=delivery.delivery_id,
        )
        while await worker.run_once() is not None:
            pass
        view = await store.inspect(delivery.delivery_id)
        results.append(f"{delivery.delivery_id}: {view.status.value}")
        broker.acknowledge(delivery)
    return results


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        journal = await open_journal(JournalSettings(path=Path(directory) / "journal.db"))
        try:
            store = JournalStore(journal)
            broker = InMemoryBroker()
            workflow = build_workflow()
            deliveries = [broker.publish(f"order-{index}", f"order-{index}") for index in range(3)]

            print("first pass:", await drain(broker, store, workflow))
            print("effects:", {key: len(value) for key, value in sorted(EFFECTS.items())})

            broker.redeliver(deliveries[0])
            print("after a redelivery:", await drain(broker, store, workflow))
            print("effects:", {key: len(value) for key, value in sorted(EFFECTS.items())})
            print("executions in the journal:", len(await store.list_executions()))
        finally:
            await journal.aclose()


def effects_for(delivery_ids: Iterable[str]) -> dict[str, int]:
    """Return how many external effects each delivery produced, for assertions in a test."""
    return {delivery_id: len(EFFECTS.get(delivery_id, [])) for delivery_id in delivery_ids}


if __name__ == "__main__":
    asyncio.run(main())
