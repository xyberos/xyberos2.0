class KernelError(RuntimeError):
    """Base exception for kernel runtime failures."""


class SubsystemShutdownError(KernelError):
    """Raised after all initialized subsystems have been given a shutdown attempt."""

    def __init__(self, failures: list[tuple[str, Exception]]) -> None:
        self.failures = failures
        names = ", ".join(name for name, _ in failures)
        super().__init__(f"Subsystem shutdown failed for: {names}")
