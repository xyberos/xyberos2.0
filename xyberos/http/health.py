from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Mapping

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from xyberos.kernel.runtime import XyberosKernel

ReadinessProbe = Callable[[], Awaitable[None]]
logger = logging.getLogger("xyberos.http.health")


def create_health_routes(
    kernel: XyberosKernel,
    prefix: str = "/health",
    *,
    probes: Mapping[str, ReadinessProbe] | None = None,
    probe_timeout_seconds: float = 1.0,
) -> list[Route]:
    """Create liveness and readiness endpoints with optional bounded dependency probes."""
    if not prefix.startswith("/") or prefix.endswith("/"):
        raise ValueError("Health route prefix must start with '/' and not end with '/'.")
    if (
        not isinstance(probe_timeout_seconds, (int, float))
        or isinstance(probe_timeout_seconds, bool)
        or probe_timeout_seconds <= 0
    ):
        raise ValueError("Probe timeout must be a positive finite number.")
    try:
        timeout = float(probe_timeout_seconds)
    except OverflowError as exc:
        raise ValueError("Probe timeout must be a positive finite number.") from exc
    if not math.isfinite(timeout):
        raise ValueError("Probe timeout must be a positive finite number.")
    configured_probes = dict(probes or {})
    for name, probe in configured_probes.items():
        if not isinstance(name, str) or not name.strip() or not callable(probe):
            raise ValueError("Readiness probes require non-empty names and callables.")

    async def live(_: Request) -> JSONResponse:
        health = kernel.health
        return JSONResponse(
            {"live": health.live},
            status_code=200 if health.live else 503,
        )

    async def ready(_: Request) -> JSONResponse:
        health = kernel.health
        dependencies: dict[str, str] = {}
        dependencies_ready = health.ready
        if health.ready:
            for name, probe in configured_probes.items():
                try:
                    await asyncio.wait_for(probe(), timeout=timeout)
                except Exception as exc:
                    logger.warning(
                        "Readiness probe '%s' failed (%s).",
                        name,
                        type(exc).__name__,
                    )
                    dependencies[name] = "unavailable"
                    dependencies_ready = False
                else:
                    dependencies[name] = "ready"
        return JSONResponse(
            {
                "ready": dependencies_ready,
                "state": health.state.value,
                "active_work": health.active_work,
                "dependencies": dependencies,
            },
            status_code=200 if dependencies_ready else 503,
        )

    return [
        Route(f"{prefix}/live", live, methods=["GET"]),
        Route(f"{prefix}/ready", ready, methods=["GET"]),
    ]
