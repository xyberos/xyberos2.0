from __future__ import annotations

from typing import Protocol

from starlette.requests import Request

from xyberos.kernel.security import AuthenticatedIdentity


class IdentityResolver(Protocol):
    """Application-supplied adapter that verifies credentials and returns identity."""

    async def __call__(self, request: Request) -> AuthenticatedIdentity | None:
        """Return a verified identity or None when authentication fails."""
