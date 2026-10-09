class KernelError(RuntimeError):
    """Base exception for kernel runtime failures."""


class KernelNotReadyError(KernelError):
    """Raised when work is submitted while the kernel is not accepting work."""


class ShutdownDrainTimeoutError(KernelError):
    def __init__(self, active_work: int, timeout_seconds: float) -> None:
        self.active_work = active_work
        self.timeout_seconds = timeout_seconds
        super().__init__(
            f"Kernel drain timed out after {timeout_seconds:g}s with "
            f"{active_work} active work item(s); subsystems remain open."
        )


class SubsystemShutdownError(KernelError):
    """Raised after all initialized subsystems have been given a shutdown attempt."""

    def __init__(self, failures: list[tuple[str, Exception]]) -> None:
        self.failures = failures
        names = ", ".join(name for name, _ in failures)
        super().__init__(f"Subsystem shutdown failed for: {names}")
