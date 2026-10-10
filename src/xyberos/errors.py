"""Framework error types with safe, actionable context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xyberos.execution.models import Attempt, StepOutcome


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


class PluginError(XyberosError):
    """Base class for plugin failures.

    ``plugin`` names the plugin and ``phase`` names the lifecycle phase, so a failure is always
    attributable. The original exception is preserved as the cause; plugin failures never echo
    configuration values.
    """

    def __init__(self, message: str, *, plugin: str, phase: str) -> None:
        self.plugin = plugin
        self.phase = phase
        super().__init__(message)


class PluginValidationError(PluginError):
    """Raised when a plugin is malformed, duplicated, or fails to register."""

    def __init__(self, message: str, *, plugin: str) -> None:
        super().__init__(message, plugin=plugin, phase="registration")


class PluginCompatibilityError(PluginValidationError):
    """Raised when a plugin targets an unsupported plugin API version."""


class PluginConfigurationError(PluginValidationError):
    """Raised when a plugin's configuration is missing, unknown, or invalid."""


class PluginDependencyError(PluginValidationError):
    """Raised when plugin requirements are missing or form a cycle."""


class PluginLifecycleError(PluginError):
    """Raised when a plugin fails during ``start`` or ``stop``."""


class TransientError(XyberosError):
    """Marker base class for a failure that a retry policy may retry.

    Retry classification is policy driven: a workflow step opts a failure into retrying either by
    raising this type (or a subclass) or by naming the exception type in its retry policy. Nothing
    else is retried, so a programming error is never silently repeated.
    """


class WorkflowError(XyberosError):
    """Base class for workflow definition and execution errors."""


class WorkflowValidationError(WorkflowError):
    """Raised when a workflow definition cannot be compiled into an executable graph.

    Validation happens before any step runs, so an invalid definition never causes partial
    execution.
    """


class WorkflowExecutionError(WorkflowError):
    """Raised when a workflow stops without producing a result.

    ``step`` names the step that stopped the run, ``attempts`` preserves every attempt outcome in
    order so retry behavior is inspectable, and ``outcomes`` holds the steps that already
    resolved. The message names exception types only: the original exception is preserved as the
    cause, including its own message.

    ``workflow`` is filled in by the executor when it raises this error itself. A step may raise a
    subclass with only a message to stop the run, in which case the executor replaces the error
    with its own, carrying the workflow and step context.
    """

    def __init__(
        self,
        message: str,
        *,
        workflow: str = "",
        step: str | None = None,
        attempts: Iterable[Attempt] = (),
        outcomes: Mapping[str, StepOutcome] | None = None,
    ) -> None:
        self.workflow = workflow
        self.step = step
        self.attempts = tuple(attempts)
        self.outcomes = dict(outcomes or {})
        super().__init__(message)


class RetryExhaustedError(WorkflowExecutionError):
    """Raised when a step's retry policy runs out of attempts."""


class StepTimeoutError(WorkflowExecutionError):
    """Raised when one step attempt exceeds its timeout.

    A step timeout is not retryable by default: it is not a :class:`TransientError`, so retrying a
    hung operation must be an explicit policy decision.
    """


class WorkflowTimeoutError(WorkflowExecutionError):
    """Raised when the whole workflow exceeds its deadline."""


class WorkflowCancelledError(WorkflowExecutionError):
    """Raised when cancellation was requested before or during execution."""
