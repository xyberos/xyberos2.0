"""Experimental, single-host durable execution: persisted Workflow progress in a SQLite journal.

Everything in this package is **experimental** and preview API, and it is deliberately narrow:

* **Single host, one journal file.** Workers coordinate through SQLite write locks and fencing
  tokens. There is no quorum, no distributed lock, and no multi-host ownership.
* **At-least-once, never exactly-once.** A persisted step result is not proof that an external
  effect happened exactly once. A step whose outcome is uncertain is recorded as
  ``OUTCOME_UNKNOWN``, and retrying it requires an activity policy that says so.
* **A journal is history, not a queue of jobs.** Workflow code is never persisted; the journal
  stores the definition's name, version, and fingerprint, and a resumed execution that finds a
  different definition refuses to continue.

See ``docs/durable.md`` for the operator guide and its limitations.
"""

from __future__ import annotations

import warnings

from xyberos.durable.contracts import SystemWallClock, WallClock
from xyberos.durable.definitions import (
    DefinitionLookup,
    lookup_definition,
    require_definition,
    workflow_key,
)
from xyberos.durable.journal import (
    JOURNAL_SCHEMA_VERSION,
    Journal,
    JournalSettings,
    open_journal,
)
from xyberos.durable.models import (
    CLAIMABLE_EXECUTION_STATES,
    EXECUTION_TRANSITIONS,
    STEP_TRANSITIONS,
    TERMINAL_EXECUTION_STATES,
    TERMINAL_STEP_STATES,
    ActivityPolicy,
    Claim,
    EventKind,
    EventView,
    ExecutionHandle,
    ExecutionStatus,
    ExecutionView,
    FailureKind,
    JournalStats,
    Reconciliation,
    StepState,
    StepView,
    execution_is_terminal,
    execution_transition_allowed,
    require_execution_transition,
    require_step_transition,
    step_is_terminal,
    step_transition_allowed,
)
from xyberos.durable.recovery import RecoveryReport, recover, resolve_interrupted_attempt
from xyberos.durable.scheduler import Plan, PlanKind, plan_next, select_edge
from xyberos.durable.store import JournalStore, definition_fingerprint
from xyberos.durable.worker import DurableWorker, WorkerSettings, WorkOutcome
from xyberos.errors import ExperimentalWarning

__all__ = [
    "CLAIMABLE_EXECUTION_STATES",
    "EXECUTION_TRANSITIONS",
    "JOURNAL_SCHEMA_VERSION",
    "STEP_TRANSITIONS",
    "TERMINAL_EXECUTION_STATES",
    "TERMINAL_STEP_STATES",
    "ActivityPolicy",
    "Claim",
    "DefinitionLookup",
    "DurableWorker",
    "EventKind",
    "EventView",
    "ExecutionHandle",
    "ExecutionStatus",
    "ExecutionView",
    "ExperimentalWarning",
    "FailureKind",
    "Journal",
    "JournalSettings",
    "JournalStats",
    "JournalStore",
    "Plan",
    "PlanKind",
    "Reconciliation",
    "RecoveryReport",
    "StepState",
    "StepView",
    "SystemWallClock",
    "WallClock",
    "WorkOutcome",
    "WorkerSettings",
    "definition_fingerprint",
    "execution_is_terminal",
    "execution_transition_allowed",
    "lookup_definition",
    "open_journal",
    "plan_next",
    "recover",
    "require_definition",
    "require_execution_transition",
    "require_step_transition",
    "resolve_interrupted_attempt",
    "select_edge",
    "step_is_terminal",
    "step_transition_allowed",
    "warn_experimental",
    "workflow_key",
]

_LIMITS = (
    "single-host and at-least-once only, with no exactly-once external effects, no multi-host "
    "ownership, and no arbitrary Python checkpointing"
)

_warned: set[str] = set()


def warn_experimental(what: str, *, stacklevel: int = 3, once: bool = True) -> None:
    """Emit the experimental warning for an unstable entry point.

    ``once`` keeps an application that opens one journal and starts three workers from printing the
    same warning four times: the first mention is informative, the rest are noise. Pass
    ``once=False`` when a caller needs an unconditional warning.
    """
    if once:
        if what in _warned:
            return
        _warned.add(what)
    warnings.warn(f"{what} is experimental: {_LIMITS}", ExperimentalWarning, stacklevel=stacklevel)
