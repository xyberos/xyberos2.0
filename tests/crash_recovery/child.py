"""Run one durable execution and die at a named boundary.

This is the *dying half* of the process-kill harness. It is a real separate process, started by the
test, and it ends with ``os._exit`` so no cleanup, no ``finally``, and no atexit hook runs: only
what was committed to the journal survives, which is exactly the property under test.

Boundaries match the failure table in ``PLAN.md`` section 5.3:

=========================== =======================================================
``before-step``             claimed, then died before the step started
``during-activity``         recorded the attempt start and the effect, then died
``after-result``            recorded the step result, then died before moving on
``before-final``            recorded the last step result, then died before completing
``during-lease-renewal``    renewed the lease (as a heartbeat does), then died mid-step
=========================== =======================================================

Usage: ``python child.py <boundary> <journal-path>``

The process prints ``EXECUTION <id>`` (flushed) once the execution is submitted, then a ``REACHED
<boundary>`` marker immediately before exiting, so the test can assert both that the crash happened
where it was asked to and what the journal kept.

Lease renewal is performed by calling the same store method the heartbeat calls rather than by
waiting for a real heartbeat. That keeps the harness deterministic; the *scheduling* of heartbeats
is covered by the virtual-clock tests in ``tests/durable/test_worker.py``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

BOUNDARIES = (
    "before-step",
    "during-activity",
    "after-result",
    "before-final",
    "during-lease-renewal",
)

# Exit codes are distinct per boundary so a wrong crash point is a failing test, not a passing one.
EXIT_CODES = {
    "before-step": 70,
    "during-activity": 71,
    "after-result": 72,
    "before-final": 73,
    "during-lease-renewal": 74,
}

EXECUTION_ID = "crash-demo-execution"


def bootstrap_paths() -> None:
    """Put the repository's ``src`` and ``tests`` roots on ``sys.path``.

    pytest's ``pythonpath`` setting only affects the pytest process, so a child started with the
    interpreter has to set its own import roots up before it imports anything of ours.
    """
    root_path = Path(__file__).resolve().parents[2]
    for candidate in (root_path / "src", root_path / "tests"):
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def die(boundary: str) -> None:
    """Print the marker and end the process without running any cleanup."""
    print(f"REACHED {boundary}", flush=True)
    os._exit(EXIT_CODES[boundary])


def _require(condition: bool, message: str) -> None:
    if not condition:  # pragma: no cover - a harness precondition, not a tested behavior
        raise AssertionError(message)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {Path(argv[0]).name} <boundary> <journal-path>", file=sys.stderr)
        return 2
    boundary, journal_path = argv[1], Path(argv[2]).resolve()
    if boundary not in BOUNDARIES:
        expected = ", ".join(BOUNDARIES)
        print(f"unknown boundary {boundary!r}; expected one of {expected}", file=sys.stderr)
        return 2

    bootstrap_paths()

    import asyncio

    from crash_recovery.definition import (
        charge,
        crash_workflow,
        input_for,
        receipt,
        step_context,
    )
    from xyberos.durable import JournalSettings, JournalStore, open_journal

    async def run() -> int:
        journal = await open_journal(JournalSettings(path=journal_path, lease_ttl_seconds=30.0))
        store = JournalStore(journal)
        value = input_for(journal_path)
        await store.submit(crash_workflow(), input=value, execution_id=EXECUTION_ID)
        print(f"EXECUTION {EXECUTION_ID}", flush=True)

        claim = await store.claim_next("dying-worker")
        _require(claim is not None, "the child could not claim the execution it just submitted")
        if boundary == "before-step":
            die(boundary)

        await store.start_step(claim, "charge")
        if boundary == "during-lease-renewal":
            # The lease is renewed the way a heartbeat renews it, then the process dies mid-step
            # with the lease still live: the case where the previous owner is *unknown* rather than
            # absent.
            await store.renew_lease(claim)
        charged = await charge(value, step_context("charge"))
        if boundary in ("during-activity", "during-lease-renewal"):
            die(boundary)
        await store.complete_step(claim, "charge", charged)
        if boundary == "after-result":
            die(boundary)

        await store.yield_execution(claim, reason="advancing to the second step")
        second = await store.claim_next("dying-worker")
        _require(second is not None, "the child could not claim the execution after yielding")
        await store.start_step(second, "receipt")
        completed = await receipt(charged, step_context("receipt"))
        await store.complete_step(second, "receipt", completed)
        die(boundary)
        return 0  # pragma: no cover - die() never returns

    return asyncio.run(run())


if __name__ == "__main__":
    sys.exit(main(sys.argv))
