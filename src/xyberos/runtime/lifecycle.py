"""Lifecycle states for a single application instance."""

from enum import Enum


class LifecycleState(str, Enum):
    """The states an application can enter during its lifetime."""

    NEW = "new"
    VALIDATED = "validated"
    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
