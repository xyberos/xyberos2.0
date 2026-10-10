"""A separately distributed plugin package: request metrics.

This package is a stand-in for a third-party plugin distribution. It imports only public
``xyberos`` names, so it proves that an independently authored plugin does not need runtime
internals. Plugins are trusted code; this one is intentionally simple.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated

from xyberos import Inject, Plugin

if TYPE_CHECKING:
    from xyberos import App

__all__ = ["Metrics", "MetricsConfig", "MetricsPlugin", "SummaryPlugin"]


@dataclass(frozen=True)
class MetricsConfig:
    """Configuration for :class:`MetricsPlugin`."""

    prefix: str = "metrics"
    limit: int = 100


class Metrics:
    """The capability contributed by the plugin."""

    def __init__(self, prefix: str, limit: int) -> None:
        self.prefix = prefix
        self.limit = limit
        self.events: list[str] = []

    def record(self, name: str) -> None:
        """Record one event, keeping only the most recent ``limit`` events."""
        if len(self.events) >= self.limit:
            self.events.pop(0)
        self.events.append(name)


class MetricsPlugin(Plugin[MetricsConfig]):
    """Contributes the :class:`Metrics` service and a ``/metrics`` route."""

    name = "metrics"
    api_version = "1"
    config_type = MetricsConfig

    def __init__(self) -> None:
        self.metrics: Metrics | None = None
        self.started = False
        self.stopped = False

    def register(self, app: App, config: MetricsConfig) -> None:
        metrics = Metrics(config.prefix, config.limit)
        self.metrics = metrics
        app.provide(Metrics, instance=metrics)
        app.get("/metrics")(self._read_metrics)

    async def _read_metrics(self, metrics: Annotated[Metrics, Inject()]) -> dict[str, object]:
        return {"prefix": metrics.prefix, "events": list(metrics.events)}

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class SummaryPlugin(Plugin[None]):
    """A dependent plugin: it requires ``metrics`` and reuses its service."""

    name = "summary"
    api_version = "1"
    requires = ("metrics",)
    config_type = None

    def __init__(self) -> None:
        self.started = False

    def register(self, app: App, config: None) -> None:
        app.get("/metrics/summary")(self._read_summary)

    async def _read_summary(self, metrics: Annotated[Metrics, Inject()]) -> dict[str, object]:
        return {"count": len(metrics.events)}

    async def start(self) -> None:
        self.started = True
