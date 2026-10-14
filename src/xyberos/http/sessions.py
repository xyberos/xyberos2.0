"""Server-side sessions, with the store left to the application.

A session is a small mutable mapping that a handler reads and writes, and the middleware loads it
before the handler runs and persists it after. Two decisions make this the framework's shape rather
than something the application has to assemble:

- **The cookie carries an opaque, signed id, not the data.** Starlette's own session middleware
  signs the *payload* into the cookie, which needs ``itsdangerous`` and puts every value a handler
  stores on the wire. Here the cookie is a session id and an HMAC made from the standard library, so
  the store decides what is kept and the client only learns which key to send back.
- **The store is a protocol, and only the in-memory one ships.** Where sessions live — a table, a
  cache, a shared file — is the deployment's decision
  ([ADR 0024](../../../docs/adr/0024-sessions-and-csrf-are-middleware-in-the-http-module.md)); a
  durable store is a package beside this line, the same way an object-store backend is. The store
  this module ships is deliberately process-local and documented as such.

The middleware writes a session back **only when a handler changed it**, so a request that reads a
session costs a load and no write, and an anonymous request that stores nothing sets no cookie.

Handlers reach the session through the request, which is also how Starlette's own middleware exposes
it::

    from xyberos.http import SessionMiddleware, InMemorySessionStore

    adapter = HttpAdapter(
        app,
        middleware=(
            Middleware(SessionMiddleware, store=store, secret=os.environ["SESSION_SECRET"]),
        ),
    )

    @app.post("/login")
    async def login(request: Request) -> dict[str, str]:
        request.session["user"] = "ada"     # `scope["session"]`, the Starlette spelling
        return {"status": "signed in"}
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections.abc import Callable, Iterator, Mapping, MutableMapping
from typing import Any, Literal, Protocol, runtime_checkable

try:
    from starlette.datastructures import MutableHeaders
    from starlette.requests import HTTPConnection, Request
    from starlette.types import ASGIApp, Message, Receive, Scope, Send
except ModuleNotFoundError as error:
    from xyberos._extras import extra_error

    raise extra_error("http", error) from error

from xyberos.errors import ConfigurationError

__all__ = [
    "DEFAULT_SESSION_MAX_AGE",
    "SESSION_COOKIE",
    "InMemorySessionStore",
    "Session",
    "SessionMiddleware",
    "SessionStore",
    "get_session",
]

SESSION_COOKIE = "xyberos_session"
"""The cookie a signed session id is read from and written to."""

DEFAULT_SESSION_MAX_AGE = 14 * 24 * 60 * 60
"""How long a session lives, in seconds: fourteen days, matching the cookie default."""

_SESSION_SCOPE_KEY = "session"
"""Where the loaded session lives on the ASGI scope.

Deliberately the key Starlette's own session middleware uses, so ``request.session`` works without
this module teaching a second spelling for the same thing.
"""


def _signature(secret: bytes, session_id: str) -> str:
    """Return the URL-safe HMAC of a session id, which is what makes the cookie unforgeable."""
    digest = hmac.new(secret, session_id.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _signed(secret: bytes, session_id: str) -> str:
    return f"{session_id}.{_signature(secret, session_id)}"


def _verified(secret: bytes, cookie: str) -> str | None:
    """Return the session id a cookie carries, or ``None`` if it was not signed by ``secret``."""
    session_id, separator, signature = cookie.rpartition(".")
    if not separator or not session_id or not signature:
        return None
    if not hmac.compare_digest(signature, _signature(secret, session_id)):
        return None
    return session_id


class Session(MutableMapping[str, Any]):
    """One request's session data, loaded before a handler runs and saved after it returns.

    This is what ``request.session`` resolves to. It is a mapping, so a handler reads and writes it
    like a dictionary, and the middleware can tell a request that changed nothing from one that did
    — which is the difference between a load and a load plus a write.
    """

    def __init__(self, data: Mapping[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = dict(data or {})
        self._stored = data is not None
        self._modified = False
        self._id: str | None = None

    @property
    def id(self) -> str | None:
        """The stored session's id, or ``None`` for a session that was not persisted yet."""
        return self._id

    @property
    def is_new(self) -> bool:
        """Whether no stored session was found for this request."""
        return not self._stored

    @property
    def modified(self) -> bool:
        """Whether a handler changed the session since it was loaded."""
        return self._modified

    @property
    def is_empty(self) -> bool:
        """Whether the session holds no data, and therefore should set no cookie."""
        return not self._data

    def stored(self, session_id: str) -> None:
        """Attach the id a store assigned, once the session is persisted."""
        self._id = session_id
        self._stored = True
        self._modified = False

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._modified = True

    def __delitem__(self, key: str) -> None:
        del self._data[key]
        self._modified = True

    def __iter__(self) -> Iterator[str]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def clear(self) -> None:
        if self._data:
            self._modified = True
        self._data.clear()

    def __repr__(self) -> str:
        return f"Session({sorted(self._data)!r})"


@runtime_checkable
class SessionStore(Protocol):
    """Where session data lives between requests.

    The framework ships one implementation — :class:`InMemorySessionStore` — and the protocol is the
    seam a durable store arrives through. A store owns its own expiry discipline: ``save`` is told
    how long the session must survive, and ``load`` answers ``None`` for a session it no longer has.
    """

    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Return a stored session's data, or ``None`` if it is gone or expired."""
        ...

    async def save(self, session_id: str, data: Mapping[str, Any], *, max_age: int) -> None:
        """Persist a session's data, replacing what was there, for ``max_age`` seconds."""
        ...

    async def delete(self, session_id: str) -> None:
        """Remove a session. Deleting one that is already gone is not an error."""
        ...


class InMemorySessionStore:
    """A process-local session store, bounded in size and honest about what that costs.

    It is correct for one process and for tests, and it is *not* durable: a restart signs everyone
    out, and two workers behind one host each hold half the sessions. That is the same boundary the
    framework states for durability
    ([ADR 0015](../../../docs/adr/0015-durability-is-single-host.md)) — reach for a store beside
    this line when either matters.
    """

    def __init__(
        self, *, max_sessions: int = 10_000, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_sessions < 1:
            raise ConfigurationError("max_sessions must be at least 1")
        self._max_sessions = max_sessions
        self._clock = clock
        self._data: dict[str, tuple[dict[str, Any], float]] = {}

    @property
    def max_sessions(self) -> int:
        """How many sessions are held before the oldest are dropped."""
        return self._max_sessions

    def __len__(self) -> int:
        return len(self._data)

    async def load(self, session_id: str) -> dict[str, Any] | None:
        """Return a live session's data, dropping it first if it has expired."""
        entry = self._data.get(session_id)
        if entry is None:
            return None
        data, expires_at = entry
        if expires_at <= self._clock():
            del self._data[session_id]
            return None
        return dict(data)

    async def save(self, session_id: str, data: Mapping[str, Any], *, max_age: int) -> None:
        """Store a session, making room when the ceiling is reached."""
        self._evict_expired()
        while len(self._data) >= self._max_sessions and session_id not in self._data:
            # Dict insertion order is age order here, so the first key is the oldest session.
            oldest = next(iter(self._data))
            del self._data[oldest]
        self._data[session_id] = (dict(data), self._clock() + max_age)

    async def delete(self, session_id: str) -> None:
        """Remove a session, whether or not it was present."""
        self._data.pop(session_id, None)

    def _evict_expired(self) -> None:
        now = self._clock()
        expired = [key for key, (_, expires_at) in self._data.items() if expires_at <= now]
        for key in expired:
            del self._data[key]


def _cookie_header(
    name: str,
    value: str,
    *,
    path: str,
    max_age: int,
    samesite: str,
    secure: bool,
) -> str:
    """Render a ``Set-Cookie`` value.

    Written rather than delegated to a response object because the middleware sits on the ``send``
    path and only has the response's headers, not the response itself.
    """
    parts = [
        f"{name}={value}",
        f"path={path}",
        f"Max-Age={max_age}",
        "httponly",
        f"samesite={samesite}",
    ]
    if secure:
        parts.append("secure")
    return "; ".join(parts)


class SessionMiddleware:
    """Load a session from its signed cookie, and store it back when a handler changed it.

    The application passes it in the adapter's middleware slot and owns the store and the secret::

        HttpAdapter(app, middleware=(Middleware(SessionMiddleware, store=store, secret=secret),))

    Position in the stack matters once, and the default is right: the middleware sits inside error
    normalization, so a request that fails still releases its session load, and a failure that never
    reaches the router — a 403 from ``CSRFMiddleware`` — leaves the cookie untouched.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        store: SessionStore,
        secret: str,
        cookie_name: str = SESSION_COOKIE,
        max_age: int = DEFAULT_SESSION_MAX_AGE,
        path: str = "/",
        samesite: Literal["lax", "strict", "none"] = "lax",
        secure: bool = False,
    ) -> None:
        if not secret:
            raise ConfigurationError("session secret must not be empty")
        if max_age < 1:
            raise ConfigurationError("max_age must be at least 1 second")
        self.app = app
        self.store = store
        self._secret = secret.encode("utf-8")
        self.cookie_name = cookie_name
        self.max_age = max_age
        self.path = path
        self.samesite = samesite
        self.secure = secure

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        session = await self._load(scope)
        scope[_SESSION_SCOPE_KEY] = session

        async def capture(message: Message) -> None:
            # The session is written when the response starts rather than after the application
            # returns, because `Set-Cookie` has to be on the message *before* it is sent — a header
            # appended to a message that has already gone out is a header nobody receives.
            if message["type"] == "http.response.start":
                await self._persist(session, MutableHeaders(scope=message))
            await send(message)

        await self.app(scope, receive, capture)

    async def _load(self, scope: Scope) -> Session:
        cookie = HTTPConnection(scope).cookies.get(self.cookie_name)
        if cookie is None:
            return Session()
        session_id = _verified(self._secret, cookie)
        if session_id is None:
            return Session()
        data = await self.store.load(session_id)
        if data is None:
            return Session()
        session = Session(data)
        session.stored(session_id)
        return session

    async def _persist(self, session: Session, headers: MutableHeaders) -> None:
        """Write the session back, and the cookie with it, only when there is something to write."""
        if session.is_empty:
            if session.id is not None:
                # The handler emptied a stored session: forget it and expire the cookie.
                await self.store.delete(session.id)
                headers.append(
                    "Set-Cookie",
                    _cookie_header(
                        self.cookie_name,
                        "",
                        path=self.path,
                        max_age=0,
                        samesite=self.samesite,
                        secure=self.secure,
                    ),
                )
            return

        session_id = session.id
        if session_id is None:
            session_id = secrets.token_urlsafe(32)
        if not session.modified and session.id is not None:
            # Loaded, used, and unchanged: nothing to store and no reason to re-issue the cookie.
            return

        await self.store.save(session_id, dict(session), max_age=self.max_age)
        session.stored(session_id)
        headers.append(
            "Set-Cookie",
            _cookie_header(
                self.cookie_name,
                _signed(self._secret, session_id),
                path=self.path,
                max_age=self.max_age,
                samesite=self.samesite,
                secure=self.secure,
            ),
        )


def get_session(request: Request) -> Session:
    """Return the request's session, or explain that the middleware is missing.

    ``request.session`` works too — the middleware stores the session where Starlette looks for it —
    and this function is the same thing with a type a checker can use and a failure that names the
    fix rather than raising ``AssertionError``.
    """
    session = request.scope.get(_SESSION_SCOPE_KEY)
    if not isinstance(session, Session):
        raise ConfigurationError(
            "no session on this request: pass SessionMiddleware in "
            "HttpAdapter(app, middleware=(Middleware(SessionMiddleware, store=..., secret=...),))"
        )
    return session
