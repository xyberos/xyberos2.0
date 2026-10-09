from __future__ import annotations

import re
import sys
import uuid

from xyberos.http.authentication import IdentityResolver
from starlette.requests import Request
from starlette.responses import JSONResponse

from xyberos.kernel.contracts import ExecutionContext, ExecutionContextAccessor
from xyberos.kernel.errors import KernelNotReadyError
from xyberos.kernel.runtime import XyberosKernel
from xyberos.kernel.security import AuthenticatedIdentity

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class XyberosContextMiddleware:
    """ASGI adapter that installs context only from trusted authentication output."""

    def __init__(
        self,
        app,
        identity_resolver: IdentityResolver | None = None,
        excluded_paths: tuple[str, ...] = (),
    ) -> None:
        self.app = app
        self.identity_resolver = identity_resolver
        self.excluded_paths = frozenset(excluded_paths)

    async def __call__(self, scope, receive, send) -> None:
        if (
            scope["type"] != "http"
            or scope.get("path") in self.excluded_paths
        ):
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


class KernelAdmissionMiddleware:
    """Reject new HTTP work while the kernel is starting or draining."""

    def __init__(
        self,
        app,
        kernel: XyberosKernel,
        excluded_paths: tuple[str, ...] = ("/health/live", "/health/ready"),
    ) -> None:
        self.app = app
        self.kernel = kernel
        self.excluded_paths = frozenset(excluded_paths)

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http" or scope.get("path") in self.excluded_paths:
            await self.app(scope, receive, send)
            return

        work = self.kernel.work()
        try:
            await work.__aenter__()
        except KernelNotReadyError:
            await JSONResponse(
                {"detail": "Service is not ready to accept requests."},
                status_code=503,
                headers={"retry-after": "1"},
            )(scope, receive, send)
            return

        try:
            await self.app(scope, receive, send)
        except BaseException:
            await work.__aexit__(*sys.exc_info())
            raise
        else:
            await work.__aexit__(None, None, None)
