"""The definition the crash harness runs, shared by the dying child and the recovering parent.

Both processes must see the *same* definition: recovery refuses to continue against a different
one, which is a guarantee worth testing rather than working around. Importing the definition from
one module is what keeps the two in step.

Each step appends a line to a side-effect file, so the parent can count how many times an effect
actually happened. That counter is how the harness distinguishes the documented policies from each
other: a re-used result leaves one line, a retried attempt leaves two, and a parked execution leaves
one with nothing recorded in the journal.
"""

from __future__ import annotations

from pathlib import Path

from xyberos import StepContext, Workflow
from xyberos.execution.policies import CancellationToken, SystemClock

CHARGE = "charge"
RECEIPT = "receipt"
JOURNAL_KEY = "journal"


def step_context(step: str) -> StepContext:
    """Return the context a step receives, for the harness's direct step calls.

    The child calls a step the way the worker would, so the side effect lands exactly where a real
    attempt would put it. A production caller never builds its own ``StepContext``; the executor
    does.
    """
    return StepContext(
        workflow="crash-demo",
        version="1",
        step=step,
        attempt=1,
        cancellation=CancellationToken(),
        clock=SystemClock(),
    )


def effects_path(journal_path: Path) -> Path:
    """Return the side-effect log for one harness run."""
    return journal_path.with_suffix(".effects")


def record_effect(journal_path: Path, name: str) -> None:
    """Append one line to the side-effect log, standing in for an external effect."""
    with effects_path(journal_path).open("a", encoding="utf-8") as handle:
        handle.write(f"{name}\n")


def count_effects(journal_path: Path, name: str) -> int:
    """Return how many times ``name`` was recorded, or ``0`` when nothing was recorded."""
    path = effects_path(journal_path)
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line == name)


async def charge(value: dict[str, str], context: StepContext) -> dict[str, str]:
    """Record an effect, then hand the journal path on so the next step can record its own."""
    record_effect(journal_of(value), CHARGE)
    return {JOURNAL_KEY: str(value[JOURNAL_KEY]), "status": "charged"}


async def receipt(value: dict[str, str], context: StepContext) -> str:
    """Record a second effect, so re-running the last step is observable too."""
    record_effect(journal_of(value), RECEIPT)
    return f"receipt for {value['status']}"


def journal_of(value: object) -> Path:
    """Return the journal path carried through the run's input."""
    if not isinstance(value, dict) or JOURNAL_KEY not in value:
        raise AssertionError(f"the crash harness input must carry a journal path, got {value!r}")
    return Path(str(value[JOURNAL_KEY]))


def input_for(journal_path: Path) -> dict[str, str]:
    """Return the run input both processes use."""
    return {JOURNAL_KEY: str(journal_path)}


def crash_workflow() -> Workflow:
    """Return the two-step definition the harness crashes and resumes."""
    return (
        Workflow("crash-demo", version="1")
        .step(CHARGE, charge)
        .step(RECEIPT, receipt)
        .edge(CHARGE, RECEIPT)
    )


def incompatible_workflow() -> Workflow:
    """Return a same-name, same-version definition with a different shape.

    Recovery must refuse it rather than resume work it cannot match, so the harness needs a
    definition that differs in exactly that way and in no other.
    """
    return (
        Workflow("crash-demo", version="1")
        .step(CHARGE, charge)
        .step("renamed", receipt)
        .edge(CHARGE, "renamed")
    )
