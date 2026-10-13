"""Framework error types with safe, actionable context."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xyberos.execution.models import Attempt, StepOutcome

# Every module that documents a public surface declares it, so the surface cannot drift by accident
# when an internal import changes. Importing a name from here still works either way; `__all__` is
# what `import *` and the surface audit use.
__all__ = [
    "AIConfigurationError",
    "AIError",
    "AIInvalidPayloadError",
    "AIModelNotFoundError",
    "AIRateLimitError",
    "AIRefusalError",
    "AIRequestError",
    "AISchemaError",
    "AITimeoutError",
    "AIToolError",
    "AITransportError",
    "AIUnsupportedCapabilityError",
    "ConfigurationError",
    "DatabaseConfigurationError",
    "DatabaseConnectionError",
    "DatabaseError",
    "DependencyCycleError",
    "DependencyError",
    "DependencyResolutionError",
    "DurableConfigurationError",
    "DurableConflictError",
    "DurableError",
    "DurableLeaseError",
    "DurableOutcomeUnknownError",
    "DurablePayloadError",
    "DurableSchemaError",
    "DurableStateError",
    "DurableVersionError",
    "ExperimentalWarning",
    "HttpError",
    "LifecycleError",
    "LifecycleStateError",
    "MissingProviderError",
    "PluginCompatibilityError",
    "PluginConfigurationError",
    "PluginDependencyError",
    "PluginError",
    "PluginLifecycleError",
    "PluginValidationError",
    "RegistrationError",
    "RequestValidationError",
    "RetryExhaustedError",
    "RouteRegistrationError",
    "ScopeViolationError",
    "ShutdownError",
    "StepTimeoutError",
    "StorageConfigurationError",
    "StorageError",
    "StorageKeyError",
    "StorageNotFoundError",
    "StorageSizeLimitError",
    "TransactionError",
    "TransientDatabaseError",
    "TransientError",
    "WorkflowCancelledError",
    "WorkflowError",
    "WorkflowExecutionError",
    "WorkflowTimeoutError",
    "WorkflowValidationError",
    "XyberosError",
]


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


class AIError(XyberosError):
    """Base class for AI facade and provider adapter failures."""


class AIConfigurationError(AIError):
    """Raised when AI configuration is missing, unknown, or unusable."""


class AIRequestError(AIError):
    """Raised when a request cannot be sent as built.

    It is not retryable: the caller has to change the request.
    """


class AITransportError(AIError, TransientError):
    """Raised when the provider could not be reached or its response was unreadable.

    It derives from :class:`TransientError` so a default retry policy retries it.
    """


class AITimeoutError(AITransportError):
    """Raised when a provider call or the request's budget ran out.

    A provider timeout is retryable, unlike a workflow step timeout, because it reports a slow or
    unreachable *service* rather than the engine's verdict on a stuck step.
    """


class AIRateLimitError(AITransportError):
    """Raised when a provider reports that the client is sending requests too quickly.

    It is retryable for the same reason a transport failure is: the request itself was valid, and a
    later attempt may succeed.
    """


class AIInvalidPayloadError(AITransportError):
    """Raised when the provider's response envelope is not the documented shape.

    Missing fields and unreadable bodies are treated as service faults because the connection or an
    intermediary is the likely cause.
    """


class AIModelNotFoundError(AIError):
    """Raised when the configured model is not available on the provider."""

    def __init__(self, message: str, *, model: str) -> None:
        self.model = model
        super().__init__(message)


class AIUnsupportedCapabilityError(AIError):
    """Raised when the model or adapter does not support what the request needs.

    Capabilities are declared, not inferred: a provider that accepts a request field may still
    ignore it, so an unsupported capability is refused before any call is made.
    """

    def __init__(self, message: str, *, capability: str, model: str = "") -> None:
        self.capability = capability
        self.model = model
        super().__init__(message)


class AIRefusalError(AIError):
    """Raised when a provider reports that the model refused the request.

    Refusals are only raised when a provider signals one explicitly; Xyberos never guesses a refusal
    from response text.
    """


class AISchemaError(AIError):
    """Raised when a payload does not validate against a declared schema.

    It is deliberately not a :class:`TransientError`: a shape mismatch is a contract or prompt
    problem, so retrying it has to be an explicit policy decision.
    """


class AIToolError(AIError):
    """Raised when a tool call is unknown, not allowed, or carries invalid arguments."""

    def __init__(self, message: str, *, tool: str) -> None:
        self.tool = tool
        super().__init__(message)


class ExperimentalWarning(UserWarning):
    """Emitted by an unstable entry point before it does anything.

    Experimental API is preview API with an explicit non-guarantee list: it may change in a `0.x`
    minor release, and its limits (single-host, at-least-once) are part of the contract.
    """


class DurableError(XyberosError):
    """Base class for durable-execution failures."""


class DurableConfigurationError(DurableError):
    """Raised when journal or executor settings are missing, unknown, or unusable."""


class DurableSchemaError(DurableError):
    """Raised when the journal schema is missing, older than the package, or newer than it."""


class DurableStateError(DurableError):
    """Raised when a requested transition is not legal from the current persisted state."""


class DurableLeaseError(DurableError):
    """Raised when a worker no longer owns the lease, or its fencing token is stale.

    A stale worker keeps running but can no longer commit state; every write is guarded by
    ownership and the fencing token, so recovery never has to trust a worker that stopped
    heartbeating.
    """

    def __init__(self, message: str, *, execution_id: str, fence: int | None = None) -> None:
        self.execution_id = execution_id
        self.fence = fence
        super().__init__(message)


class DurableConflictError(DurableError):
    """Raised when a submission or claim collides with existing, different work."""


class DurableVersionError(DurableError):
    """Raised when a resumable execution does not match the supplied workflow definition."""


class DurablePayloadError(DurableError):
    """Raised when an input, output, or result cannot be persisted safely.

    Payloads must be JSON-serializable and within the configured size limit, because the journal
    stores them verbatim and a durable execution has to be resumable from its records alone.
    """


class DurableOutcomeUnknownError(DurableError):
    """Raised when an interrupted attempt may or may not have produced its external effect.

    It is deliberately not a :class:`TransientError`: retrying an operation whose effect is
    uncertain is a decision the caller has to make explicit, through idempotency or a reconciler.
    """


class StorageError(XyberosError):
    """Base class for storage failures.

    A backend that can fail transiently — a remote object store, a network filesystem — raises a
    subclass that is also a :class:`TransientError`, so a retry decision stays a classification
    rather than a guess. The shipped local-filesystem provider owns no remote resource and never
    raises one.
    """


class StorageConfigurationError(StorageError):
    """Raised when storage settings are missing, unknown, or unusable."""


class StorageKeyError(StorageError):
    """Raised when a key is not a usable storage key.

    A key is a relative, forward-slash-separated path with no empty, ``.``, or ``..`` segment, so a
    key can never name something outside the space it was given. The refusal is an error rather
    than a silent normalization, because a caller that meant to escape has a bug worth seeing.
    """


class StorageNotFoundError(StorageError):
    """Raised when a key was never stored, or has been deleted.

    Reading a missing object is an error rather than a ``None``, because a read that silently
    yields nothing turns an absent object into an ``AttributeError`` somewhere further away.
    """


class StorageSizeLimitError(StorageError):
    """Raised when an object exceeds the ceiling its provider was configured with.

    The ceiling belongs to the provider (``Storage.max_object_bytes``) rather than to the call, so
    the contract suite can check the boundary at exactly one byte over it.
    """
