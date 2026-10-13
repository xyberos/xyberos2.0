"""Read-only diagnostics for a composed application."""

from __future__ import annotations

from dataclasses import dataclass

from xyberos.plugins.protocol import PluginInfo


@dataclass(frozen=True)
class ProviderInfo:
    """A read-only description of one registered provider.

    ``dependencies`` are the contracts this provider's factory declares, by name. They are part of
    the description rather than something a reader derives, because the CLI explains a resolution
    path from this snapshot: two implementations of "what depends on what" would be one too many.
    """

    contract: str
    scope: str
    eager: bool
    source: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class Diagnostics:
    """A snapshot of provider sources and plugin order, for troubleshooting."""

    providers: tuple[ProviderInfo, ...]
    plugins: tuple[PluginInfo, ...]

    def render(self) -> str:
        """Return a human-readable report of providers and plugins."""
        lines = ["providers:"]
        lines.extend(
            f"  {provider.contract} [{provider.scope}"
            f"{', eager' if provider.eager else ''}] from {provider.source}"
            for provider in self.providers
        )
        lines.append("plugins:")
        if self.plugins:
            lines.extend(f"  {plugin.render()}" for plugin in self.plugins)
        else:
            lines.append("  (none)")
        return "\n".join(lines)


__all__ = ["Diagnostics", "ProviderInfo"]
