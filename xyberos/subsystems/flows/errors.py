from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .contracts import StepTrace


class FlowError(RuntimeError):
    """Base class for flow execution failures."""


class FlowExecutionError(FlowError):
    def __init__(
        self,
        flow_name: str,
        step_name: str,
        attempts: int,
        trace: tuple[StepTrace, ...],
    ) -> None:
        self.flow_name = flow_name
        self.step_name = step_name
        self.attempts = attempts
        self.trace = trace
        super().__init__(
            f"Flow '{flow_name}' failed at step '{step_name}' "
            f"after {attempts} attempt(s)."
        )


class FlowTimeoutError(FlowError):
    def __init__(
        self,
        flow_name: str,
        step_name: str | None = None,
        trace: tuple[StepTrace, ...] = (),
    ) -> None:
        self.flow_name = flow_name
        self.step_name = step_name
        self.trace = trace
        location = f" at step '{step_name}'" if step_name else ""
        super().__init__(f"Flow '{flow_name}' timed out{location}.")


class FlowObserverError(FlowError):
    def __init__(self, flow_name: str, cause: Exception) -> None:
        self.flow_name = flow_name
        self.cause = cause
        super().__init__(f"Trace observer failed while running flow '{flow_name}'.")
