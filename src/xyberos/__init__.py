"""Public package boundary for Xyberos.

Phase 1 exposes the application runtime: composition, typed configuration, dependency
injection, lifecycle, context/logging helpers, and the framework error taxonomy. Optional
capabilities such as HTTP, databases, AI, Flow, and durable execution stay internal until
their contracts are validated in later phases.
"""

from xyberos.app import App, RequestContext
from xyberos.config import AppSettings, Settings, load_settings
from xyberos.diagnostics import Diagnostics, ProviderInfo
from xyberos.errors import (
    ConfigurationError,
    DatabaseConfigurationError,
    DatabaseConnectionError,
    DatabaseError,
    DependencyCycleError,
    DependencyError,
    DependencyResolutionError,
    HttpError,
    LifecycleError,
    LifecycleStateError,
    MissingProviderError,
    PluginCompatibilityError,
    PluginConfigurationError,
    PluginDependencyError,
    PluginError,
    PluginLifecycleError,
    PluginValidationError,
    RegistrationError,
    RequestValidationError,
    RouteRegistrationError,
    ScopeViolationError,
    ShutdownError,
    TransactionError,
    TransientDatabaseError,
    XyberosError,
)
from xyberos.plugins.protocol import (
    PLUGIN_API_VERSION,
    Plugin,
    PluginInfo,
    PluginState,
)
from xyberos.plugins.registry import PluginRegistry
from xyberos.routing import Route, RouteRegistry
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
    "DatabaseConfigurationError",
    "DatabaseConnectionError",
    "DatabaseError",
    "Dependency",
    "DependencyCycleError",
    "DependencyError",
    "DependencyResolutionError",
    "Diagnostics",
    "HttpError",
    "Inject",
    "LifecycleError",
    "LifecycleState",
    "LifecycleStateError",
    "MissingProviderError",
    "PLUGIN_API_VERSION",
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
    "Route",
    "RouteRegistrationError",
    "RouteRegistry",
    "Scope",
    "ScopeViolationError",
    "Settings",
    "ShutdownError",
    "TransactionError",
    "TransientDatabaseError",
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
