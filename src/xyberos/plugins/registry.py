"""Plugin registration, requirement ordering, and lifecycle execution.

A plugin's declared requirements must already be registered when it is added, so registration
order is dependency order and startup order is deterministic. That also makes requirement cycles
structurally impossible.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from xyberos.errors import PluginDependencyError, PluginLifecycleError, PluginValidationError
from xyberos.plugins.config import build_plugin_config
from xyberos.plugins.protocol import Plugin, PluginInfo, PluginState, validate_plugin

if TYPE_CHECKING:
    from xyberos.app import App

LOGGER = logging.getLogger("xyberos.plugins")


@dataclass
class _PluginEntry:
    plugin: Plugin[Any]
    config: object | None
    state: PluginState = PluginState.REGISTERED


class PluginRegistry:
    """An application-local set of plugins in deterministic dependency order."""

    def __init__(self) -> None:
        self._entries: dict[str, _PluginEntry] = {}
        self._active: list[str] = []

    @property
    def active_source(self) -> str | None:
        """Return ``plugin:<name>`` while a plugin is registering, otherwise ``None``."""
        return f"plugin:{self._active[-1]}" if self._active else None

    def enter(self, name: str) -> None:
        """Attribute registrations made inside a plugin's ``register`` hook."""
        self._active.append(name)

    def exit(self) -> None:
        """End the current plugin registration scope."""
        self._active.pop()

    @property
    def names(self) -> tuple[str, ...]:
        """Return plugin names in start order."""
        return tuple(self._entries)

    def state(self, name: str) -> PluginState | None:
        """Return one plugin's current state, or ``None`` when it is not registered."""
        entry = self._entries.get(name)
        return None if entry is None else entry.state

    def describe(self) -> tuple[PluginInfo, ...]:
        """Return read-only descriptions in start order."""
        return tuple(
            PluginInfo(
                name=entry.plugin.name,
                api_version=getattr(entry.plugin, "api_version", ""),
                requires=tuple(getattr(entry.plugin, "requires", ())),
                state=entry.state,
                config_type=getattr(entry.plugin, "config_type", None),
            )
            for entry in self._entries.values()
        )

    def add(
        self,
        app: App,
        plugin: Plugin[Any],
        *,
        config: Mapping[str, object] | None = None,
    ) -> str:
        """Validate, configure, and register one plugin, returning its name."""
        name = validate_plugin(plugin)
        if name in self._entries:
            raise PluginValidationError(
                f"a plugin named {name!r} is already registered", plugin=name
            )
        self._ensure_requirements_registered(plugin, name)

        options = dict(config) if config is not None else dict(app.settings.plugin_options(name))
        typed = build_plugin_config(plugin.config_type, options, plugin=name)

        self.enter(name)
        try:
            plugin.register(app, typed)
        except Exception as error:
            raise PluginValidationError(
                f"plugin {name!r} failed to register: {error}", plugin=name
            ) from error
        finally:
            self.exit()
        self._entries[name] = _PluginEntry(plugin=plugin, config=typed)
        return name

    async def start_all(self) -> None:
        """Start every plugin in order; stop the ones already started if one fails."""
        started: list[_PluginEntry] = []
        for entry in self._entries.values():
            try:
                await entry.plugin.start()
            except BaseException as error:
                cleanup = await _stop_entries(reversed(started))
                if isinstance(error, Exception):
                    raise PluginLifecycleError(
                        _lifecycle_message(entry.plugin.name, "start", error, cleanup),
                        plugin=entry.plugin.name,
                        phase="start",
                    ) from error
                raise
            entry.state = PluginState.STARTED
            started.append(entry)

    async def stop_all(self) -> tuple[tuple[str, BaseException], ...]:
        """Stop every started plugin in reverse order, collecting failures."""
        return await _stop_entries(reversed(list(self._entries.values())))

    def _ensure_requirements_registered(self, plugin: Plugin[Any], name: str) -> None:
        missing = [required for required in plugin.requires if required not in self._entries]
        if missing:
            listed = ", ".join(sorted(missing))
            raise PluginDependencyError(
                f"plugin {name!r} requires {listed}, which must be registered first",
                plugin=name,
            )


async def _stop_entries(
    entries: reversed[_PluginEntry] | list[_PluginEntry],
) -> tuple[tuple[str, BaseException], ...]:
    """Stop the given entries, returning the plugins whose stop hook failed."""
    failures: list[tuple[str, BaseException]] = []
    for entry in entries:
        if entry.state is not PluginState.STARTED:
            continue
        try:
            await entry.plugin.stop()
        except BaseException as error:
            entry.state = PluginState.FAILED
            if isinstance(error, Exception):
                failures.append((f"plugin:{entry.plugin.name}", error))
                LOGGER.warning("plugin %r failed to stop: %s", entry.plugin.name, error)
                continue
            raise
        else:
            entry.state = PluginState.STOPPED
    return tuple(failures)


def _lifecycle_message(
    name: str,
    phase: str,
    error: BaseException,
    cleanup: tuple[tuple[str, BaseException], ...],
) -> str:
    message = f"plugin {name!r} failed during {phase}: {error}"
    if cleanup:
        failed = ", ".join(resource for resource, _ in cleanup)
        message += f" (cleanup also failed for: {failed})"
    return message
