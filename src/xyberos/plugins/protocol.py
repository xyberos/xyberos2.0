"""The trusted, in-process plugin contract.

Plugins are ordinary Python code. Xyberos provides no sandbox, permission model, or protection
from a plugin that misbehaves: only add plugins you trust, exactly as you would import a library.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar, Generic, TypeVar

from xyberos.errors import PluginCompatibilityError, PluginValidationError

if TYPE_CHECKING:
    from xyberos.app import App

PLUGIN_API_VERSION = "1"
PLUGIN_API_MAJOR = PLUGIN_API_VERSION.split(".", 1)[0]

ConfigT = TypeVar("ConfigT")


class PluginState(str, Enum):
    """The lifecycle state of one registered plugin."""

    REGISTERED = "registered"
    STARTED = "started"
    STOPPED = "stopped"
    FAILED = "failed"


@dataclass(frozen=True)
class PluginInfo:
    """A read-only description of one registered plugin."""

    name: str
    api_version: str
    requires: tuple[str, ...]
    state: PluginState
    config_type: type[object] | None = None
    """The plugin's declared configuration dataclass, when it has one.

    Carried here rather than looked up elsewhere because it *is* plugin metadata: `xyberos check
    --schema` describes each declared plugin's section from it, and the runtime already validates
    that same type.
    """

    def render(self) -> str:
        """Return a single-line description for diagnostics output."""
        requires = ", ".join(self.requires) if self.requires else "-"
        return f"{self.name} {self.api_version} [{self.state.value}] requires: {requires}"


class Plugin(Generic[ConfigT], ABC):
    """Base class for a trusted, in-process capability plugin.

    Subclasses declare immutable metadata and register their capabilities:

    .. code-block:: python

        class MetricsPlugin(Plugin[MetricsConfig]):
            name = "metrics"
            api_version = "1"
            requires = ("database",)
            config_type = MetricsConfig

            def register(self, app: App, config: MetricsConfig) -> None:
                app.provide(Metrics, instance=Metrics(config.prefix))

    ``register`` runs once, while the application is still mutable, and is where a plugin supplies
    providers and routes. ``start`` and ``stop`` are optional: they manage the plugin's own
    resources after app-scoped providers are constructed and before they are closed.
    """

    name: ClassVar[str]
    api_version: ClassVar[str] = PLUGIN_API_VERSION
    requires: ClassVar[tuple[str, ...]] = ()
    config_type: ClassVar[type[object] | None] = None

    @abstractmethod
    def register(self, app: App, config: ConfigT) -> None:
        """Register this plugin's providers and routes. Called once, before startup."""

    async def start(self) -> None:
        """Prepare plugin-owned resources; runs after app-scoped providers are constructed."""

    async def stop(self) -> None:
        """Release plugin-owned resources; runs before app-owned resources are closed."""


def validate_plugin(plugin: Plugin[Any]) -> str:
    """Validate plugin metadata and return its name."""
    name = plugin_name(plugin)
    api_version = getattr(plugin, "api_version", PLUGIN_API_VERSION)
    if not isinstance(api_version, str) or not api_version.strip():
        raise PluginValidationError(
            f"plugin {name!r} must declare a non-empty api_version", plugin=name
        )
    major = api_version.split(".", 1)[0]
    if major != PLUGIN_API_MAJOR:
        raise PluginCompatibilityError(
            f"plugin {name!r} targets plugin API {api_version!r}, but this runtime supports "
            f"{PLUGIN_API_VERSION!r}",
            plugin=name,
        )
    requires = getattr(plugin, "requires", ())
    if not isinstance(requires, tuple) or any(not isinstance(item, str) for item in requires):
        raise PluginValidationError(
            f"plugin {name!r} must declare requires as a tuple of plugin names", plugin=name
        )
    return name


def plugin_name(plugin: Plugin[Any]) -> str:
    """Return a validated plugin name."""
    name = getattr(plugin, "name", "")
    if not isinstance(name, str) or not name.strip():
        raise PluginValidationError(
            "every plugin must declare a non-empty name", plugin="<unnamed>"
        )
    if not name.replace("-", "_").isidentifier():
        raise PluginValidationError(
            f"plugin name {name!r} must be an identifier so it can be used as a configuration key",
            plugin=name,
        )
    return name
