"""Test utilities for the HTTP adapter.

Starlette's test client is built on ``httpx``, which the optional ``http`` extra provides.
"""

from __future__ import annotations

from starlette.testclient import TestClient
from starlette.types import ASGIApp

from xyberos.http.adapter import HttpAdapter


def create_test_client(target: HttpAdapter | ASGIApp) -> TestClient:
    """Return a Starlette test client for an adapter or a bare ASGI application.

    Use the client as a context manager so the ASGI lifespan runs; the runtime is only ready to
    accept requests once startup has completed.
    """
    if isinstance(target, HttpAdapter):
        return TestClient(target.asgi_app)
    return TestClient(target)
