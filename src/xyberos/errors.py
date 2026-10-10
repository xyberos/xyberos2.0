"""Framework error types with safe, actionable context."""

from __future__ import annotations

from collections.abc import Iterable


class XyberosError(Exception):
    """Base class for errors raised by Xyberos."""


class ConfigurationError(XyberosError):
    """Raised when typed configuration cannot be loaded or validated."""


class RegistrationError(XyberosError):
    """Raised when a provider registration is invalid or ambiguous."""


class DependencyError(XyberosError):
    """Base class for provider graph and resolution errors."""

    def __init__(self, message: str, *, path: Iterable[object] = ()) -> None:
        self.path = tuple(path)
        super().__init__(message)


class MissingProviderError(DependencyError):
    """Raised when a declared dependency has no provider."""


class DependencyCycleError(DependencyError):
    """Raised when provider registrations contain a cycle."""


class ScopeViolationError(DependencyError):
    """Raised when a longer-lived service captures a shorter-lived dependency."""


class DependencyResolutionError(DependencyError):
    """Raised when a registered provider cannot create a valid instance."""


class LifecycleError(XyberosError):
    """Raised when application lifecycle transitions cannot be completed."""


class LifecycleStateError(LifecycleError):
    """Raised when an operation is invalid in the current lifecycle state."""


class ShutdownError(LifecycleError):
    """Raised after every managed resource has been given a chance to close."""

    def __init__(self, failures: Iterable[tuple[str, BaseException]]) -> None:
        self.failures = tuple(error for _, error in failures)
        self.resources = tuple(name for name, _ in failures)
        joined = ", ".join(self.resources) or "unknown resource"
        super().__init__(f"{len(self.failures)} managed resource(s) failed to close: {joined}")
