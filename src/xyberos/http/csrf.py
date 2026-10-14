"""Cross-site request forgery protection, as a middleware the application passes.

CSRF is the one browser attack with a canonical defence, and the defence needs no store, no policy,
and no third-party package — which is why it belongs in this module rather than in a package beside
the framework
([ADR 0024](../../../docs/adr/0024-sessions-and-csrf-are-middleware-in-the-http-module.md)).
Sessions were refused for a different reason — the store is a deployment decision — and only the
store moved to a package. The two are separate deliberately: an application with no login can still
want the origin check, and one that keeps its session in a signed cookie needs no store at all.

Two checks run, and either can refuse a request:

1. **The origin check is the primary defence.** A browser attaches ``Origin`` (or, failing that,
   ``Referer``) to a state-changing request, and a cross-site one names the attacker's site. A
   request whose ``Origin`` names another site is refused, which is what stops a form on
   ``evil.example`` from posting to your application with the user's cookies attached. A request
   with no ``Origin`` and no ``Referer`` is not a browser cross-site request, so it is not refused
   by this check — an API client using ``curl`` would otherwise have to invent an origin header.
2. **The token check is the belt to that braces.** A token is written to a readable cookie and can
   be sent back in ``X-CSRF-Token``; when a token is presented it must match, so an attacker who
   can attach a cookie but cannot read it still fails. Set ``require_token=True`` to demand the
   header on every state-changing request, which is the right setting for an application with no
   browsers at all or a policy that insists on double submission.

The session cookie should still be ``SameSite=Lax`` — the default when you use
:class:`~xyberos.http.SessionMiddleware` — because the two together are what make the simple cases
impossible rather than merely unlikely.

Set ``trusted_origins`` when the application is reached through a proxy or several hostnames, and
keep the session cookie's ``samesite`` narrower than ``none`` unless a cross-site form is genuinely
required.
"""

from __future__ import annotations

import hmac
import secrets
from typing import Literal
from urllib.parse import urlsplit

try:
    from starlette.datastructures import Headers, MutableHeaders
    from starlette.requests import HTTPConnection, Request
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("http", error) from error

from xyberos.errors import ConfigurationError, CSRFError

__all__ = [
    "CSRF_COOKIE",
    "CSRF_HEADER",
    "SAFE_METHODS",
    "CSRFMiddleware",
    "get_csrf_token",
]

CSRF_COOKIE = "xyberos_csrf"
"""The cookie the token is written to. Readable on purpose: a page has to echo it back."""

CSRF_HEADER = "X-CSRF-Token"
"""The header a state-changing request presents the token in."""

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
"""Methods that do not change state, and so are not required to present a token."""

DEFAULT_TOKEN_MAX_AGE = 365 * 24 * 60 * 60
"""How long the token cookie lives, in seconds: a year, because it carries no secret of its own."""

_CSRF_SCOPE_KEY = "csrf_token"


class CSRFMiddleware:
    """Refuse state-changing requests that did not come from this origin.

    The application passes it in the adapter's middleware slot and owns the policy::

        HttpAdapter(app, middleware=(Middleware(CSRFMiddleware, trusted_origins=("https://app.example",)),))

    It sits inside error normalization like every other application middleware, so a refusal is a
    ``403`` with the framework's usual error body rather than an internal error.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        cookie_name: str = CSRF_COOKIE,
        header_name: str = CSRF_HEADER,
        require_token: bool = False,
        trusted_origins: tuple[str, ...] = (),
        max_age: int = DEFAULT_TOKEN_MAX_AGE,
        path: str = "/",
        samesite: Literal["lax", "strict", "none"] = "lax",
        secure: bool = False,
    ) -> None:
        if max_age < 1:
            raise ConfigurationError("max_age must be at least 1 second")
        self.app = app
        self.cookie_name = cookie_name
        self.header_name = header_name
        self.require_token = require_token
        self.trusted_origins = frozenset(origin.rstrip("/").lower() for origin in trusted_origins)
        self.max_age = max_age
        self.path = path
        self.samesite = samesite
        self.secure = secure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        presented_cookie = HTTPConnection(scope).cookies.get(self.cookie_name)
        token = presented_cookie or secrets.token_urlsafe(32)
        scope[_CSRF_SCOPE_KEY] = token

        if _method(scope) not in SAFE_METHODS:
            self._check(scope, headers, token)

        issued = presented_cookie is None

        async def send_with_cookie(message: Message) -> None:
            if issued and message["type"] == "http.response.start":
                MutableHeaders(scope=message).append("Set-Cookie", _cookie_header(self, token))
            await send(message)

        await self.app(scope, receive, send_with_cookie)

    def _check(self, scope: Scope, headers: Headers, token: str) -> None:
        presented = headers.get(self.header_name)
        if presented is not None and not hmac.compare_digest(presented, token):
            raise CSRFError("the CSRF token does not match the one issued to this browser")
        if self.require_token and presented is None:
            raise CSRFError(f"this request must present a {self.header_name} header")

        origin = _request_origin(headers)
        if origin is None:
            # No Origin and no usable Referer: not a browser cross-site request, so the origin check
            # has nothing to judge and the token check above is the whole of the decision.
            return
        if origin not in self.trusted_origins and origin != _own_origin(scope, headers):
            raise CSRFError(f"this request came from {origin!r}, which is not this application")


def _method(scope: Scope) -> str:
    return str(scope.get("method", "GET")).upper()


def _origin_of(url: str) -> str | None:
    """Return a URL's ``scheme://host[:port]`` origin, lowercased, or ``None`` if it has none."""
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        return None
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def _request_origin(headers: Headers) -> str | None:
    """The origin a request claims, from ``Origin`` or ``Referer``, or ``None`` if it names none."""
    origin = headers.get("origin")
    if origin:
        return _origin_of(origin)
    referer = headers.get("referer")
    if referer:
        return _origin_of(referer)
    return None


def _own_origin(scope: Scope, headers: Headers) -> str:
    """The origin this request was addressed to, as the client addressed it.

    ``Host`` is used rather than ``server``, because a request reaches a handler by the name the
    client used and that is the name the browser's ``Origin`` will carry. A deployment behind a
    proxy that rewrites ``Host`` passes ``trusted_origins`` instead of relying on this.
    """
    scheme = str(scope.get("scheme", "http")).lower()
    host = headers.get("host", "").lower()
    return f"{scheme}://{host}"


def _cookie_header(middleware: CSRFMiddleware, token: str) -> str:
    """Render the token cookie.

    Not ``HttpOnly``, and that is the point: a page or a script has to read it to send it back in
    the header. It carries no authority on its own — the origin check is what makes it meaningful.
    """
    parts = [
        f"{middleware.cookie_name}={token}",
        f"path={middleware.path}",
        f"Max-Age={middleware.max_age}",
        f"samesite={middleware.samesite}",
    ]
    if middleware.secure:
        parts.append("secure")
    return "; ".join(parts)


def get_csrf_token(request: Request) -> str:
    """Return the token to embed in a page or hand to a script.

    ``CSRFMiddleware`` has to be in the stack for a request to have one; a request that reaches this
    without it is a composition mistake, and the error says so rather than returning an empty string
    a form would happily submit.
    """
    token = request.scope.get(_CSRF_SCOPE_KEY)
    if not isinstance(token, str):
        raise ConfigurationError(
            "no CSRF token on this request: pass CSRFMiddleware in "
            "HttpAdapter(app, middleware=(Middleware(CSRFMiddleware),))"
        )
    return token
