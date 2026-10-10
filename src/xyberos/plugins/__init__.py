"""Trusted, in-process plugins and their capability model."""

from xyberos.plugins.protocol import (
    PLUGIN_API_MAJOR,
    PLUGIN_API_VERSION,
    Plugin,
    PluginInfo,
    PluginState,
)
from xyberos.plugins.registry import PluginRegistry

__all__ = [
    "PLUGIN_API_MAJOR",
    "PLUGIN_API_VERSION",
    "Plugin",
    "PluginInfo",
    "PluginRegistry",
    "PluginState",
]
