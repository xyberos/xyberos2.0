"""Structured execution events.

Events carry identifiers, status, attempt numbers, and timings, and nothing else. Step input and
output values never appear, because workflow payloads routinely contain personal or secret data.
Exception messages are left out for the same reason; the raised error and the step's own logging
are where details belong.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias


class EventType(str, Enum):
    """Every state transition the executor reports."""

    WORKFLOW_STARTED = "workflow_started"
    WORKFLOW_SUCCEEDED = "workflow_succeeded"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_TIMED_OUT = "workflow_timed_out"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    STEP_STARTED = "step_started"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_FAILED = "step_failed"
    STEP_RETRIED = "step_retried"
    STEP_SKIPPED = "step_skipped"
    STEP_TIMED_OUT = "step_timed_out"
    STEP_CANCELLED = "step_cancelled"


@dataclass(frozen=True)
class WorkflowEvent:
    """One structured execution event.

    ``sequence`` counts events within a single run, so ordering is assertable without relying on
    timestamps, and ``timestamp`` comes from the executor's clock.
    """

    type: EventType
    sequence: int
    workflow: str
    version: str
    timestamp: float
    step: str | None = None
    attempt: int | None = None
    duration: float | None = None
    correlation_id: str | None = None
    detail: str | None = None
    error_type: str | None = None

    def render(self) -> str:
        """Return a single-line description for logs and test failures."""
        parts = [f"#{self.sequence}", self.type.value, f"workflow={self.workflow}"]
        if self.step is not None:
            parts.append(f"step={self.step}")
        if self.attempt is not None:
            parts.append(f"attempt={self.attempt}")
        if self.duration is not None:
            parts.append(f"duration={self.duration:.6f}")
        if self.error_type is not None:
            parts.append(f"error={self.error_type}")
        if self.detail is not None:
            parts.append(self.detail)
        return " ".join(parts)


EventSink: TypeAlias = Callable[[WorkflowEvent], None]
"""A synchronous event receiver. Sinks must not block: they run on the execution path."""
