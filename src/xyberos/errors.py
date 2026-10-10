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
        super().__init__(f"{len(self.failures)} shutdown problem(s): {joined}")


class HttpError(XyberosError):
    """Base class for HTTP adaptation errors.

    ``status_code`` is the response status the adapter uses when the error reaches it. Errors
    raised by request handling are safe to expose when they subclass this type; any other
    exception is reported as an internal server error without leaking its message.
    """

    def __init__(self, message: str, *, status_code: int = 500) -> None:
        self.status_code = status_code
        super().__init__(message)


class RouteRegistrationError(HttpError):
    """Raised when a route or its handler signature cannot be registered."""


class RequestValidationError(HttpError):
    """Raised when request input fails validation and the message is safe to expose."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 422,
        errors: Iterable[str] = (),
    ) -> None:
        self.errors = tuple(errors)
        super().__init__(message, status_code=status_code)


class DatabaseError(XyberosError):
    """Base class for database provider failures."""


class DatabaseConfigurationError(DatabaseError):
    """Raised when the database provider is configured with unsupported values."""


class DatabaseConnectionError(DatabaseError):
    """Raised when the database provider cannot open or reach the database."""


class TransactionError(DatabaseError):
    """Raised when a transaction cannot be committed or was rolled back."""


class TransientDatabaseError(DatabaseError):
    """Raised when a retryable lock failure exhausts its bounded retry budget."""
