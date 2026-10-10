"""Public package boundary for Xyberos.

Phase 1 exposes the application runtime: composition, typed configuration, dependency
injection, lifecycle, context/logging helpers, and the framework error taxonomy. Optional
capabilities such as HTTP, databases, AI, Flow, and durable execution stay internal until
their contracts are validated in later phases.
"""

from xyberos.app import App, RequestContext
from xyberos.config import AppSettings, Settings, load_settings
from xyberos.errors import (
    ConfigurationError,
    DependencyCycleError,
    DependencyError,
    DependencyResolutionError,
    LifecycleError,
    LifecycleStateError,
    MissingProviderError,
    RegistrationError,
    ScopeViolationError,
    ShutdownError,
    XyberosError,
)
from xyberos.runtime.context import (
    ContextLogFilter,
    bind_context,
    bind_correlation_id,
    bind_deadline,
    capture_context_runner,
    create_task_in_context,
    get_context,
    get_correlation_id,
    get_deadline,
)
from xyberos.runtime.dependencies import Dependency, Inject, Provider, ProviderRegistry, Scope
from xyberos.runtime.lifecycle import LifecycleState

__version__ = "0.0.0"

__all__ = [
    "App",
    "AppSettings",
    "ConfigurationError",
    "ContextLogFilter",
    "Dependency",
    "DependencyCycleError",
    "DependencyError",
    "DependencyResolutionError",
    "Inject",
    "LifecycleError",
    "LifecycleState",
    "LifecycleStateError",
    "MissingProviderError",
    "Provider",
    "ProviderRegistry",
    "RegistrationError",
    "RequestContext",
    "Scope",
    "ScopeViolationError",
    "Settings",
    "ShutdownError",
    "XyberosError",
    "__version__",
    "bind_context",
    "bind_correlation_id",
    "bind_deadline",
    "capture_context_runner",
    "create_task_in_context",
    "get_context",
    "get_correlation_id",
    "get_deadline",
    "load_settings",
]
