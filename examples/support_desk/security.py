"""Who is calling, established by something that checked the assertion.

Xyberos ships no identity model and no authorization model (see
``docs/adr/0014-no-identity-or-authorization-model.md``). What it provides is the shape this module
is written in: an `HttpError` with the status you choose, a component that verifies rather than
believes, and a principal that travels as a required argument.

The tenant is part of the principal rather than part of the request, which is the difference
between a multi-tenant application and a claim a client can edit: a payload that names a tenant
cannot change which rows the service looks at.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Iterable
from dataclasses import dataclass

from starlette.requests import Request

from xyberos import HttpError

SUBJECT_HEADER = "X-Authenticated-Subject"
TENANT_HEADER = "X-Authenticated-Tenant"
ROLES_HEADER = "X-Authenticated-Roles"
SIGNATURE_HEADER = "X-Principal-Signature"
SECRET_ENV = "XYBEROS_IDENTITY_SECRET"

REQUESTER = "requester"
SUPPORT_AGENT = "support_agent"
SUPPORT_LEAD = "support_lead"

#: The two roles that may work on tickets they did not open.
STAFF = (SUPPORT_AGENT, SUPPORT_LEAD)


@dataclass(frozen=True)
class Principal:
    """Who is calling, which tenant they are in, and what the verifier established about them."""

    subject: str
    tenant: str
    roles: frozenset[str] = frozenset()

    def holds(self, *roles: str) -> bool:
        """Whether the principal carries any of these roles."""
        return any(role in self.roles for role in roles)


class UnauthenticatedError(HttpError):
    """The assertion was missing, unsigned, or signed by something else; exposed as a 401."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the request is not authenticated: {reason}", status_code=401)


class ForbiddenError(HttpError):
    """The caller is known and may not do this; exposed as a 403."""

    def __init__(self, requirement: str) -> None:
        super().__init__(f"this operation requires {requirement}", status_code=403)


def require_role(principal: Principal, *roles: str) -> None:
    """Refuse a principal that carries none of these roles, as a `403`."""
    if not principal.holds(*roles):
        raise ForbiddenError(" or ".join(roles))


class PrincipalVerifier:
    """Turns a signed assertion into a principal, or refuses.

    The secret is configuration, and a deployment without one refuses every request rather than
    trusting the request: the failure is closed, and it is a 401 rather than a crash.
    """

    def __init__(self, secret: str | None = None) -> None:
        self._secret = (secret if secret is not None else os.environ.get(SECRET_ENV, "")).encode()

    def verify(self, request: Request) -> Principal:
        """Return the verified principal for a request, or raise `UnauthenticatedError`."""
        if not self._secret:
            raise UnauthenticatedError(f"no identity secret is configured in {SECRET_ENV}")
        subject = request.headers.get(SUBJECT_HEADER, "")
        tenant = request.headers.get(TENANT_HEADER, "")
        roles = request.headers.get(ROLES_HEADER, "")
        signature = request.headers.get(SIGNATURE_HEADER, "")
        if not subject or not tenant:
            raise UnauthenticatedError(f"{SUBJECT_HEADER} and {TENANT_HEADER} are both required")
        if not hmac.compare_digest(signature, self.sign(subject, tenant, roles)):
            raise UnauthenticatedError("the assertion signature does not match")
        return Principal(subject=subject, tenant=tenant, roles=_roles(roles))

    def sign(self, subject: str, tenant: str, roles: str = "") -> str:
        """Return the signature a caller must present for this subject, tenant, and roles."""
        message = "\n".join((subject, tenant, roles)).encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def headers(self, subject: str, tenant: str, roles: Iterable[str] = ()) -> dict[str, str]:
        """Return the headers a client presents after authenticating successfully."""
        joined = ",".join(roles)
        return {
            SUBJECT_HEADER: subject,
            TENANT_HEADER: tenant,
            ROLES_HEADER: joined,
            SIGNATURE_HEADER: self.sign(subject, tenant, joined),
        }


def _roles(raw: str) -> frozenset[str]:
    return frozenset(role.strip() for role in raw.split(",") if role.strip())
