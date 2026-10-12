"""An in-tree plugin: a capability, two routes, its configuration, and a plugin that requires it.

A distribution usually ships several plugins in one package, which is why both classes live here.
The first one is self-contained; the second one declares ``requires = ("audit",)`` and therefore
cannot be registered before it — the registry refuses the wrong order instead of discovering it at
request time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from starlette.requests import Request

from xyberos import App, Inject, Plugin
from xyberos.http import read_json_object


@dataclass(frozen=True)
class AuditConfig:
    """Typed configuration, read from ``[plugins.audit]`` or the environment."""

    prefix: str = "audit"
    limit: int = 100


class AuditLog:
    """The capability this plugin contributes to the application."""

    def __init__(self, prefix: str, limit: int) -> None:
        self.prefix = prefix
        self.limit = limit
        self.events: list[str] = []

    def record(self, event: str) -> None:
        """Record one event, keeping only the most recent ``limit`` of them."""
        if len(self.events) >= self.limit:
            self.events.pop(0)
        self.events.append(event)


class AuditPlugin(Plugin[AuditConfig]):
    """Contributes the log, a route that reads it, and a route that writes to it."""

    name = "audit"
    api_version = "1"
    config_type = AuditConfig

    def __init__(self) -> None:
        self.started = False
        self.stopped = False

    def register(self, app: App, config: AuditConfig) -> None:
        app.provide(AuditLog, instance=AuditLog(config.prefix, config.limit))
        app.get("/audit")(self._read)
        app.post("/audit")(self._record)

    async def _read(self, log: Annotated[AuditLog, Inject()]) -> dict[str, object]:
        return {"prefix": log.prefix, "events": list(log.events)}

    async def _record(
        self, request: Request, log: Annotated[AuditLog, Inject()]
    ) -> dict[str, object]:
        payload = await read_json_object(request)
        log.record(str(payload.get("event", "")))
        return {"events": list(log.events)}

    async def start(self) -> None:
        """Runs after app-scoped providers are constructed, before they are closed."""
        self.started = True

    async def stop(self) -> None:
        """Runs before app-owned resources are closed, and after every provider was constructed."""
        self.stopped = True


class ReportsPlugin(Plugin[None]):
    """A dependent plugin: it needs the log, so the registry makes the order a requirement."""

    name = "reports"
    api_version = "1"
    requires = ("audit",)
    config_type = None

    def register(self, app: App, config: None) -> None:
        app.get("/reports")(self._summary)

    async def _summary(self, log: Annotated[AuditLog, Inject()]) -> dict[str, object]:
        return {"count": len(log.events)}
