from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Callable, Mapping, Protocol, TypeAlias


class ExecutionPolicy(str, Enum):
    ASYNC = "async"
    SYNC = "sync"
    THREAD = "thread"
    PROCESS = "process"


@dataclass
class FlowState:
    """Flow input and named outputs produced by completed steps."""

    input: Any
    outputs: dict[str, Any] = field(default_factory=dict)
    dependencies: Mapping[str, Any] = field(default_factory=dict)


StepHandler: TypeAlias = Callable[[FlowState], Any]
StepCondition: TypeAlias = Callable[[FlowState], bool]


@dataclass(frozen=True)
class RetryPolicy:
    """Explicit retry rules; retries require idempotent step behavior."""

    max_attempts: int = 1
    delay_seconds: float = 0
    retry_on: tuple[type[Exception], ...] = ()

    def __post_init__(self) -> None:
        if (
            not isinstance(self.max_attempts, int)
            or isinstance(self.max_attempts, bool)
            or self.max_attempts < 1
        ):
            raise ValueError("Retry max_attempts must be at least one.")
        if (
            not isinstance(self.delay_seconds, (int, float))
            or isinstance(self.delay_seconds, bool)
            or not math.isfinite(self.delay_seconds)
            or self.delay_seconds < 0
        ):
            raise ValueError("Retry delay_seconds cannot be negative.")
        if self.max_attempts > 1 and not self.retry_on:
            raise ValueError("Retries require explicit retry_on exception types.")
        if not all(
            isinstance(exception_type, type)
            and issubclass(exception_type, Exception)
            for exception_type in self.retry_on
        ):
            raise ValueError("retry_on must contain Exception types.")


@dataclass(frozen=True)
class FlowStep:
    name: str
    handler: StepHandler
    policy: ExecutionPolicy = ExecutionPolicy.ASYNC
    timeout_seconds: float | None = None
    condition: StepCondition | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    idempotent: bool = False

    def __post_init__(self) -> None:
        if not callable(self.handler):
            raise ValueError("Flow step handler must be callable.")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Flow step name must not be empty.")
        if self.condition is not None and not callable(self.condition):
            raise ValueError("Flow step condition must be callable.")
        if self.timeout_seconds is not None:
            _validate_timeout(self.timeout_seconds, "Flow step")
        if self.retry.max_attempts > 1 and not self.idempotent:
            raise ValueError(
                f"Flow step '{self.name}' must be marked idempotent before retries."
            )


@dataclass(frozen=True)
class FlowDefinition:
    name: str
    steps: tuple[FlowStep, ...]
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Flow name must not be empty.")
        if not isinstance(self.steps, tuple) or not all(
            isinstance(step, FlowStep) for step in self.steps
        ):
            raise ValueError("Flow steps must be a tuple of FlowStep instances.")
        if self.timeout_seconds is not None:
            _validate_timeout(self.timeout_seconds, "Flow")
        names = [step.name for step in self.steps]
        if len(names) != len(set(names)):
            raise ValueError(f"Flow '{self.name}' contains duplicate step names.")


def _validate_timeout(timeout: float, owner: str) -> None:
    if (
        not isinstance(timeout, (int, float))
        or isinstance(timeout, bool)
        or not math.isfinite(timeout)
        or timeout <= 0
    ):
        raise ValueError(f"{owner} timeout_seconds must be a positive finite number.")


@dataclass(frozen=True)
class StepTrace:
    step_name: str
    status: str
    attempts: int
    duration_seconds: float


TraceObserver: TypeAlias = Callable[[StepTrace], Any]


@dataclass(frozen=True)
class FlowResult:
    flow_name: str
    state: FlowState
    trace: tuple[StepTrace, ...]


class FlowEngineContract(Protocol):
    async def run(self, flow: FlowDefinition, input_value: Any) -> FlowResult:
        """Execute a flow and return its final state and execution trace."""
