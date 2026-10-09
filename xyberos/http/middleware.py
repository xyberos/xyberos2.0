from __future__ import annotations

import re
import uuid

from xyberos.http.authentication import IdentityResolver
from starlette.requests import Request
from starlette.responses import JSONResponse

from xyberos.kernel.contracts import ExecutionContext, ExecutionContextAccessor
from xyberos.kernel.security import AuthenticatedIdentity

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class XyberosContextMiddleware:
    """ASGI adapter that installs context only from trusted authentication output."""

    def __init__(self, app, identity_resolver: IdentityResolver | None = None) -> None:
        self.app = app
        self.identity_resolver = identity_resolver

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        if self.identity_resolver is None:
            await JSONResponse(
                {"detail": "Authentication is not configured."},
                status_code=401,
            )(scope, receive, send)
            return

        identity = await self.identity_resolver(request)
        if identity is None:
            await JSONResponse(
                {"detail": "Authentication required."},
                status_code=401,
            )(scope, receive, send)
            return
        if not isinstance(identity, AuthenticatedIdentity):
            raise TypeError("Identity resolver must return AuthenticatedIdentity or None.")

        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if _SAFE_REQUEST_ID.fullmatch(supplied_request_id)
            else str(uuid.uuid4())
        )
        context = ExecutionContext(
            request_id=request_id,
            tenant_id=identity.tenant_id,
            actor_id=identity.actor_id,
            metadata={"path": request.url.path, "method": request.method},
        )
        token = ExecutionContextAccessor.set(context)

        async def send_with_request_id(message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            ExecutionContextAccessor.reset(token)
