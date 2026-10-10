"""Explicit, inspectable execution: direct calls and the in-process workflow engine.

This package has no optional dependencies. A workflow definition imports no HTTP, database, AI, or
durable module, so the whole execution layer works in a core-only installation.
"""

from xyberos.execution.direct import direct
from xyberos.execution.events import EventSink, EventType, WorkflowEvent
from xyberos.execution.executor import WorkflowExecutor
from xyberos.execution.models import (
    DIRECT_WORKFLOW,
    Attempt,
    BranchPredicate,
    Edge,
    InputType,
    Step,
    StepFunction,
    StepOutcome,
    StepStatus,
    Workflow,
    WorkflowResult,
)
from xyberos.execution.policies import (
    Backoff,
    CancellationToken,
    Clock,
    Retry,
    StepContext,
    SystemClock,
    milliseconds,
    minutes,
    seconds,
)
from xyberos.execution.testing import (
    FakeExternalService,
    MalformedResponseError,
    ManualClock,
    RateLimitError,
    Reply,
    TransientServiceError,
    pending_tasks,
)

__all__ = [
    "DIRECT_WORKFLOW",
    "Attempt",
    "Backoff",
    "BranchPredicate",
    "CancellationToken",
    "Clock",
    "Edge",
    "EventSink",
    "EventType",
    "FakeExternalService",
    "InputType",
    "MalformedResponseError",
    "ManualClock",
    "RateLimitError",
    "Reply",
    "Retry",
    "Step",
    "StepContext",
    "StepFunction",
    "StepOutcome",
    "StepStatus",
    "SystemClock",
    "TransientServiceError",
    "Workflow",
    "WorkflowEvent",
    "WorkflowExecutor",
    "WorkflowResult",
    "direct",
    "milliseconds",
    "minutes",
    "pending_tasks",
    "seconds",
]
