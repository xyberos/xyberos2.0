from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from .lifecycle import LifecycleState


@dataclass(frozen=True)
class KernelHealth:
    live: bool
    ready: bool
    state: LifecycleState
    active_work: int


@dataclass(frozen=True)
class KernelEvent:
    name: str
    component: str
    outcome: str
    occurred_at: datetime
    duration_seconds: float | None = None
    error_type: str | None = None


class KernelObserver(Protocol):
    def __call__(self, event: KernelEvent) -> None:
        """Consume a metadata-only kernel lifecycle event."""
