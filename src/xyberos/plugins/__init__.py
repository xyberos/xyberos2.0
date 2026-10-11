"""Trusted, in-process plugins and their capability model."""

from xyberos.plugins.protocol import PLUGIN_API_VERSION, Plugin, PluginInfo, PluginState
from xyberos.plugins.registry import PluginRegistry

# `PLUGIN_API_MAJOR` is the internal component the compatibility check compares, not something a
# plugin author writes: they declare `api_version`, and the registry reads `PLUGIN_API_VERSION`.
__all__ = [
    "PLUGIN_API_VERSION",
    "Plugin",
    "PluginInfo",
    "PluginRegistry",
    "PluginState",
]
