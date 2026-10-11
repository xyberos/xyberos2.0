# broker_worker example

How to run durable work at a scale beyond one process without pretending the framework distributes it:
**the queue owns delivery, the journal owns progress**
([ADR 0015](../../docs/adr/0015-durability-is-single-host.md)).

## Run it

```powershell
python examples/broker_worker/app.py
```

```text
first pass: ['order-0: completed', 'order-1: completed', 'order-2: completed']
effects: {'order-0': 2, 'order-1': 2, 'order-2': 2}
after a redelivery: ['order-0: completed']
effects: {'order-0': 2, 'order-1': 2, 'order-2': 2}
executions in the journal: 3
```

Read the last three lines together. `order-0` was delivered **twice**, was acknowledged once, and
still produced exactly two effects (one charge, one notification) and one execution. That is the
property the whole pattern exists for.

```powershell
pytest tests/integration/test_broker_worker_example.py
```

## The pattern

```python
for delivery in broker.receive():
    await store.submit(
        workflow,
        input=delivery.payload,
        execution_id=delivery.delivery_id,  # stable across redeliveries
        submission_key=delivery.delivery_id,
    )
    while await worker.run_once() is not None:
        pass
    broker.acknowledge(delivery)  # only after the execution is terminal
```

| Step | Why it is shaped that way |
| --- | --- |
| `execution_id = delivery id` | submission is idempotent for the same id and the same definition, so a redelivered item reuses the completed execution instead of repeating its effects |
| run until `run_once()` returns `None` | one step per claim is the crash boundary; the loop is what "run this item to completion" means |
| acknowledge **after** the work | acknowledging first turns a crash into lost work; acknowledging last turns it into redelivery, which is now harmless |
| `ActivityPolicy(idempotent=True)` on each step | it tells recovery that replaying this step is safe, which is what makes a mid-step crash recoverable rather than parked |

## What this is not

- **Not a distributed scheduler.** Everything runs on one host against one journal file. Many worker
  processes on that host is supported; many hosts is not.
- **Not exactly-once.** The journal gives at-least-once with a durable record of how far the work got.
  The step's own effect still has to be idempotent — the pattern makes duplicates *recoverable*, not
  impossible.
- **Not a broker.** `InMemoryBroker` is a stand-in to keep the example runnable. Use the queue you
  already operate, and make sure its delivery ids are stable: a broker that mints a fresh id per
  delivery defeats the whole design, silently.
- **Not for a workload that outgrows the machine.** If one host cannot hold the journal, the answer is
  a system built for cross-host orchestration (Temporal, Argo, a managed workflow service), with this
  runtime as the worker.
