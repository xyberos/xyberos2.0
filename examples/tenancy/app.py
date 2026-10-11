"""A tenancy recipe: the verified principal is an argument, never ambient authority.

Xyberos ships no identity or authorization model
([ADR 0014](../../docs/adr/0014-no-identity-or-authorization-model.md)), so this example is the
*shape* to build one in, and it is the smallest shape that is correct:

- one component verifies an incoming assertion — here an HMAC over tenant and subject, which is what
  makes a header trusted rather than merely present;
- the verified principal is passed to the service **as an argument**, so its signature cannot be
  satisfied without one and forgetting it is a type error rather than a cross-tenant read;
- the tenant never comes from the request payload, and the tests prove that a payload claiming a
  different tenant changes nothing;
- context values are not used for any of this. They are diagnostic only
  ([security guide](../../docs/security.md)); a tenant in `contextvars` would be ambient authority.

In production the verifier would check a token signature or call your identity provider, and your
proxy would strip any client-supplied assertion header. The HMAC here stands in for that check and
keeps the example runnable with no service.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from typing import Annotated

from starlette.requests import Request

from xyberos import App, HttpError, Inject, Settings
from xyberos.http import HttpAdapter, read_json_object
from xyberos.http.testing import create_test_client

TENANT_HEADER = "X-Tenant"
SUBJECT_HEADER = "X-Subject"
SIGNATURE_HEADER = "X-Principal-Signature"


@dataclass(frozen=True)
class Principal:
    """Who is calling, and on whose behalf. The only thing a service is allowed to trust."""

    tenant: str
    subject: str


class UnauthenticatedError(HttpError):
    """The caller's assertion was missing, malformed, or not signed by the shared secret."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the request is not authenticated: {reason}", status_code=401)


class PrincipalVerifier:
    """Turns a signed assertion into a principal, or refuses.

    A header is trusted because something verified it, not because it arrived. The secret belongs in
    the environment; here it is a constructor argument so the example stays self-contained.
    """

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def verify(self, request: Request) -> Principal:
        """Return the verified principal for a request, or raise `UnauthenticatedError`."""
        tenant = request.headers.get(TENANT_HEADER, "")
        subject = request.headers.get(SUBJECT_HEADER, "")
        signature = request.headers.get(SIGNATURE_HEADER, "")
        if not tenant or not subject:
            raise UnauthenticatedError(f"{TENANT_HEADER} and {SUBJECT_HEADER} are required")
        if not hmac.compare_digest(signature, self.sign(tenant, subject)):
            raise UnauthenticatedError("the assertion signature does not match")
        return Principal(tenant=tenant, subject=subject)

    def sign(self, tenant: str, subject: str) -> str:
        """Return the signature a caller must present for ``tenant`` and ``subject``."""
        message = f"{tenant}\n{subject}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()


class TicketStore:
    """Every method takes a tenant, because there is no other honest way to scope a query.

    The tenant is a required argument rather than an injected default: a caller that forgets it
    cannot compile, and a payload that claims one is simply not consulted.
    """

    def __init__(self) -> None:
        self._rows: dict[str, list[str]] = {}

    def add(self, tenant: str, title: str) -> None:
        """Store a ticket for one tenant."""
        self._rows.setdefault(tenant, []).append(title)

    def titles(self, tenant: str) -> list[str]:
        """Return one tenant's tickets, and only that tenant's."""
        return list(self._rows.get(tenant, []))


def create_app(*, secret: str = "example-secret") -> App:
    """Compose the application: a verifier, a store, and routes that pass the principal along."""
    app = App(settings=Settings.load(environ={}, overrides={"app": {"name": "tenancy"}}))
    app.provide(TicketStore, instance=TicketStore())
    app.provide(PrincipalVerifier, instance=PrincipalVerifier(secret))

    @app.get("/tickets")
    async def list_tickets(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        store: Annotated[TicketStore, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        return {"tenant": principal.tenant, "tickets": store.titles(principal.tenant)}

    @app.post("/tickets")
    async def create_ticket(
        request: Request,
        verifier: Annotated[PrincipalVerifier, Inject()],
        store: Annotated[TicketStore, Inject()],
    ) -> dict[str, object]:
        principal = verifier.verify(request)
        payload = await read_json_object(request)
        store.add(principal.tenant, str(payload.get("title", "")))
        return {"tenant": principal.tenant, "tickets": store.titles(principal.tenant)}

    return app


def build_asgi_app(app: App) -> object:
    """Build the ASGI application an ASGI server can run."""
    return HttpAdapter(app).asgi_app


def signed_headers(verifier: PrincipalVerifier, tenant: str, subject: str) -> dict[str, str]:
    """Return the headers a client presents after authenticating."""
    return {
        TENANT_HEADER: tenant,
        SUBJECT_HEADER: subject,
        SIGNATURE_HEADER: verifier.sign(tenant, subject),
    }


def main() -> None:
    """Show the whole flow, including the two ways it refuses."""
    app = create_app()
    verifier = PrincipalVerifier("example-secret")

    with create_test_client(HttpAdapter(app)) as client:
        acme = signed_headers(verifier, "acme", "ada")
        globex = signed_headers(verifier, "globex", "linus")

        client.post("/tickets", json={"title": "printer is on fire"}, headers=acme)
        print("acme sees:", client.get("/tickets", headers=acme).json())

        client.post(
            "/tickets",
            json={"title": "badge reader is broken", "tenant": "acme"},
            headers=globex,
        )
        print("globex sees:", client.get("/tickets", headers=globex).json())
        print("acme still sees:", client.get("/tickets", headers=acme).json())

        unsigned = {TENANT_HEADER: "acme", SUBJECT_HEADER: "ada"}
        response = client.get("/tickets", headers=unsigned)
        print("unsigned status:", response.status_code)
        print("unsigned body:", response.json()["error"]["type"])


if __name__ == "__main__":
    main()
