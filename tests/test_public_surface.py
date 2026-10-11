"""The public surface is frozen here, deliberately.

The audit that produced these lists found something worth fixing: five documented modules had no
``__all__``, so their surface was whatever their imports happened to leave behind — ``Mapping``,
``dataclass``, ``json``, ``sys``, a private generic type variable. Those names were public by
accident, which means an internal refactor could have changed the public API without anyone
noticing.

So this file asserts three things per module: the module declares ``__all__``, that declaration is
exactly the set below, and every declared name is importable and documented. Adding a name is a
deliberate edit here; so is removing one, which is the point.
"""

from __future__ import annotations

import importlib
import inspect
from types import ModuleType
from typing import Any

import pytest

# The re-export surface: documented import paths, so `__all__` names come from submodules by design.
PACKAGE_SURFACES = {
    "xyberos": {
        "DIRECT_WORKFLOW",
        "PLUGIN_API_VERSION",
        "App",
        "AppSettings",
        "Attempt",
        "Backoff",
        "BranchPredicate",
        "CancellationToken",
        "Clock",
        "ConfigurationError",
        "ContextLogFilter",
        "DatabaseConfigurationError",
        "DatabaseConnectionError",
        "DatabaseError",
        "Dependency",
        "DependencyCycleError",
        "DependencyError",
        "DependencyResolutionError",
        "Diagnostics",
        "Edge",
        "EventSink",
        "EventType",
        "HttpError",
        "Inject",
        "InputType",
        "LifecycleError",
        "LifecycleState",
        "LifecycleStateError",
        "MissingProviderError",
        "Plugin",
        "PluginCompatibilityError",
        "PluginConfigurationError",
        "PluginDependencyError",
        "PluginError",
        "PluginInfo",
        "PluginLifecycleError",
        "PluginRegistry",
        "PluginState",
        "PluginValidationError",
        "Provider",
        "ProviderInfo",
        "ProviderRegistry",
        "RegistrationError",
        "RequestContext",
        "RequestValidationError",
        "Retry",
        "RetryExhaustedError",
        "Route",
        "RouteRegistrationError",
        "RouteRegistry",
        "Scope",
        "ScopeViolationError",
        "Settings",
        "ShutdownError",
        "Step",
        "StepContext",
        "StepFunction",
        "StepOutcome",
        "StepStatus",
        "StepTimeoutError",
        "SystemClock",
        "TransactionError",
        "TransientDatabaseError",
        "TransientError",
        "Workflow",
        "WorkflowCancelledError",
        "WorkflowError",
        "WorkflowEvent",
        "WorkflowExecutionError",
        "WorkflowExecutor",
        "WorkflowResult",
        "WorkflowTimeoutError",
        "WorkflowValidationError",
        "XyberosError",
        "__version__",
        "bind_context",
        "bind_correlation_id",
        "bind_deadline",
        "capture_context_runner",
        "create_task_in_context",
        "direct",
        "get_context",
        "get_correlation_id",
        "get_deadline",
        "load_settings",
        "milliseconds",
        "minutes",
        "seconds",
    },
    "xyberos.plugins": {
        "PLUGIN_API_VERSION",
        "Plugin",
        "PluginInfo",
        "PluginRegistry",
        "PluginState",
    },
    "xyberos.execution": {
        "DIRECT_WORKFLOW",
        "Attempt",
        "Backoff",
        "BranchPredicate",
        "CancellationToken",
        "Clock",
        "Edge",
        "EventSink",
        "EventType",
        "FakeExternalService",
        "InputType",
        "MalformedResponseError",
        "ManualClock",
        "RateLimitError",
        "Reply",
        "Retry",
        "Step",
        "StepContext",
        "StepFunction",
        "StepOutcome",
        "StepStatus",
        "SystemClock",
        "TransientServiceError",
        "Workflow",
        "WorkflowEvent",
        "WorkflowExecutor",
        "WorkflowResult",
        "direct",
        "milliseconds",
        "minutes",
        "pending_tasks",
        "seconds",
    },
    "xyberos.ai": {
        "DEFAULT_LOGGER_NAME",
        "AIFacade",
        "ChatChunk",
        "ChatModel",
        "ChatRequest",
        "ChatResponse",
        "EmbeddingModel",
        "EmbeddingRequest",
        "EmbeddingResponse",
        "FakeModelProvider",
        "FinishReason",
        "LoggingPolicy",
        "Message",
        "ModelCapabilities",
        "ModelHealth",
        "ModelProvider",
        "ModelReply",
        "ModelStatus",
        "Role",
        "Tool",
        "ToolCall",
        "ToolContext",
        "ToolEvent",
        "ToolEventSink",
        "ToolEventType",
        "ToolHandler",
        "ToolResult",
        "ToolSet",
        "ToolSpec",
        "Usage",
        "check_schema",
        "describe_schema",
        "validate_payload",
    },
    "xyberos.http": {
        "CompiledRoute",
        "CorrelationIdMiddleware",
        "ErrorMappingMiddleware",
        "HttpAdapter",
        "RequestScopeMiddleware",
        "build_endpoint",
        "compile_route",
        "read_json_object",
    },
    "xyberos.database": {
        "DatabaseProvider",
        "SqliteDatabase",
        "SqliteSettings",
        "TransactionOperation",
        "alembic_config",
        "apply_migrations",
        "open_database",
        "run_migrations",
        "sqlite_provider",
        "temporary_database",
    },
    "xyberos.durable": {
        "CLAIMABLE_EXECUTION_STATES",
        "EXECUTION_TRANSITIONS",
        "JOURNAL_SCHEMA_VERSION",
        "STEP_TRANSITIONS",
        "TERMINAL_EXECUTION_STATES",
        "TERMINAL_STEP_STATES",
        "ActivityPolicy",
        "Claim",
        "DefinitionLookup",
        "DurableWorker",
        "EventKind",
        "EventView",
        "ExecutionHandle",
        "ExecutionStatus",
        "ExecutionView",
        "ExperimentalWarning",
        "FailureKind",
        "Journal",
        "JournalSettings",
        "JournalStats",
        "JournalStore",
        "Plan",
        "PlanKind",
        "Reconciliation",
        "RecoveryReport",
        "StepState",
        "StepView",
        "SystemWallClock",
        "WallClock",
        "WorkerSettings",
        "WorkOutcome",
        "definition_fingerprint",
        "execution_is_terminal",
        "execution_transition_allowed",
        "lookup_definition",
        "open_journal",
        "plan_next",
        "recover",
        "require_definition",
        "require_execution_transition",
        "require_step_transition",
        "resolve_interrupted_attempt",
        "select_edge",
        "step_is_terminal",
        "step_transition_allowed",
        "warn_experimental",
        "workflow_key",
    },
}

# Implementation modules: their `__all__` names are defined *there*, not re-exported.
MODULE_SURFACES = {
    "xyberos.errors": {
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
        "TransactionError",
        "TransientDatabaseError",
        "TransientError",
        "WorkflowCancelledError",
        "WorkflowError",
        "WorkflowExecutionError",
        "WorkflowTimeoutError",
        "WorkflowValidationError",
        "XyberosError",
    },
    "xyberos.runtime.context": {
        "ContextLogFilter",
        "bind_context",
        "bind_correlation_id",
        "bind_deadline",
        "capture_context_runner",
        "create_task_in_context",
        "get_context",
        "get_correlation_id",
        "get_deadline",
    },
    "xyberos.deprecation": {
        "XyberosDeprecationWarning",
        "deprecated",
        "warn_deprecated",
    },
    "xyberos.ai.contracts": {
        "ChatChunk",
        "ChatModel",
        "ChatRequest",
        "ChatResponse",
        "EmbeddingModel",
        "EmbeddingRequest",
        "EmbeddingResponse",
        "FinishReason",
        "Message",
        "ModelCapabilities",
        "ModelHealth",
        "ModelProvider",
        "ModelStatus",
        "Role",
        "ToolCall",
        "ToolSpec",
        "Usage",
    },
    "xyberos.ai.schema": {
        "check_schema",
        "describe_schema",
        "validate_payload",
    },
    "xyberos.ai.tools": {
        "Tool",
        "ToolContext",
        "ToolEvent",
        "ToolEventSink",
        "ToolEventType",
        "ToolHandler",
        "ToolResult",
        "ToolSet",
    },
    "xyberos.execution.testing": {
        "MALFORMED_PAYLOAD",
        "FakeExternalService",
        "MalformedResponseError",
        "ManualClock",
        "RateLimitError",
        "Reply",
        "TransientServiceError",
        "pending_tasks",
    },
    "xyberos.ai.testing": {
        "DEFAULT_FAKE_MODEL",
        "FakeModelProvider",
        "ModelReply",
    },
    "xyberos.http.testing": {
        "create_test_client",
    },
    "xyberos.database.testing": {
        "assert_provider_contract",
        "temporary_database",
    },
    "xyberos.durable.testing": {
        "ManualWallClock",
        "expire_leases",
        "idempotent_activity",
    },
}

ALL_SURFACES = {**PACKAGE_SURFACES, **MODULE_SURFACES}


def declared_order(name: str) -> tuple[int, str]:
    """Order ``__all__`` the way this repo writes it: constants, then classes, then the rest.

    That is isort's ``order_by_type``, which the existing modules already follow, so the rule is
    stated once here rather than being guessed at in every new module.
    """
    if name.isupper():
        return (0, name.lower())
    if name[:1].isupper():
        return (1, name.lower())
    return (2, name.lower())


def load(name: str) -> ModuleType:
    return importlib.import_module(name)


@pytest.mark.parametrize("name", sorted(ALL_SURFACES))
def test_a_documented_module_declares_its_surface(name: str) -> None:
    module = load(name)

    assert getattr(module, "__all__", None) is not None, (
        f"{name} documents a public surface but declares no __all__, so its surface is whatever "
        "its imports leave behind"
    )


@pytest.mark.parametrize(("name", "expected"), sorted(ALL_SURFACES.items()))
def test_the_declared_surface_is_exactly_what_is_frozen(name: str, expected: set[str]) -> None:
    module = load(name)

    assert set(module.__all__) == expected, (
        f"{name}'s public surface changed; update this list deliberately, and record the change in "
        "the changelog and docs/stability.md"
    )


@pytest.mark.parametrize("name", sorted(ALL_SURFACES))
def test_every_declared_callable_documents_itself(name: str) -> None:
    """Every public class and function explains itself.

    Type aliases and data constants are excluded because they have no ``__doc__`` of their own — a
    following string literal is a convention, not a docstring — so for those the frozen set above is
    the guarantee.
    """
    module = load(name)

    undocumented = []
    for item in module.__all__:
        value = getattr(module, item)
        if inspect.isclass(value) or inspect.isfunction(value):
            if not (inspect.getdoc(value) or "").strip():
                undocumented.append(item)

    assert not undocumented, f"{name} declares undocumented callable(s): {', '.join(undocumented)}"


@pytest.mark.parametrize("name", sorted(MODULE_SURFACES))
def test_an_implementation_module_declares_only_what_it_defines(name: str) -> None:
    """An implementation module must not re-export someone else's callables by accident.

    ``from x import Y`` in a module body makes ``Y`` reachable as ``module.Y``, and declaring it in
    ``__all__`` would turn a private import into public API. Type aliases are exempt: a typing alias
    such as ``Callable[[int], str]`` legitimately reports the typing module as its ``__module__``.
    """
    module = load(name)

    borrowed = sorted(
        item
        for item in module.__all__
        if (inspect.isclass(getattr(module, item)) or inspect.isfunction(getattr(module, item)))
        and getattr(getattr(module, item), "__module__", name) != name
    )

    assert not borrowed, f"{name} re-exports callable(s) it does not define: {', '.join(borrowed)}"


@pytest.mark.parametrize("name", sorted(ALL_SURFACES))
def test_the_declared_surface_is_sorted_and_free_of_private_names(name: str) -> None:
    """``__all__`` follows the repo's ordering convention and names nothing private.

    A dunder such as ``__version__`` is a deliberate public name, so only single-underscore names
    count as private here.
    """
    module = load(name)
    declared: list[Any] = list(module.__all__)

    assert declared == sorted(declared, key=declared_order), f"{name}'s __all__ is not sorted"
    private = [
        item
        for item in declared
        if item.startswith("_") and not (item.startswith("__") and item.endswith("__"))
    ]
    assert not private, f"{name}'s __all__ names something private: {', '.join(private)}"


def test_the_root_surface_does_not_leak_submodules_into_its_declaration() -> None:
    """Importing a submodule binds it on the package, but that is not a promise to users."""
    import xyberos

    leaked = sorted(
        name for name in xyberos.__all__ if isinstance(getattr(xyberos, name), ModuleType)
    )

    assert not leaked, f"the root __all__ names submodule(s): {', '.join(leaked)}"
