"""Who is calling, established by something that checked the assertion.

Xyberos ships no identity model, and will not (see
``docs/adr/0014-no-identity-or-authorization-model.md``). What it provides is the shape this module
is written in: an `HttpError` with the status you choose, a component that verifies rather than
believes, and a principal that travels as an argument.

The rule this module exists to enforce, in one line: a header is trusted because something
*verified* it, never because it arrived. Until `verify` returns, nothing in the request is a fact
about the caller.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass

from starlette.requests import Request

from xyberos import HttpError

SUBJECT_HEADER = "X-Authenticated-Subject"
ROLES_HEADER = "X-Authenticated-Roles"
SIGNATURE_HEADER = "X-Principal-Signature"
SECRET_ENV = "XYBEROS_IDENTITY_SECRET"


@dataclass(frozen=True)
class Principal:
    """Who is calling, and what the verifier established about them."""

    subject: str
    roles: frozenset[str] = frozenset()


class UnauthenticatedError(HttpError):
    """The assertion was missing, unsigned, or signed by something else; exposed as a 401."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the request is not authenticated: {reason}", status_code=401)


class ForbiddenError(HttpError):
    """The caller is known and is not allowed to do this; exposed as a 403.

    The two statuses answer different questions, which is why they are separate classes:
    `401` means "I do not know who you are", `403` means "I know who you are, and no". A client can
    act on the first — authenticate more convincingly — and cannot act on the second.
    """

    def __init__(self, requirement: str) -> None:
        super().__init__(f"this operation requires {requirement}", status_code=403)


def require_role(principal: Principal, role: str) -> None:
    """Refuse a principal that does not carry this role, as a `403`."""
    if role not in principal.roles:
        raise ForbiddenError(f"the {role} role")


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
        roles = request.headers.get(ROLES_HEADER, "")
        signature = request.headers.get(SIGNATURE_HEADER, "")
        if not subject:
            raise UnauthenticatedError(f"{SUBJECT_HEADER} is required")
        if not hmac.compare_digest(signature, self.sign(subject, roles)):
            raise UnauthenticatedError("the assertion signature does not match")
        return Principal(subject=subject, roles=_roles(roles))

    def sign(self, subject: str, roles: str = "") -> str:
        """Return the signature a caller must present for this subject and these roles."""
        message = f"{subject}\n{roles}".encode()
        return hmac.new(self._secret, message, hashlib.sha256).hexdigest()

    def headers(self, subject: str, roles: str = "") -> dict[str, str]:
        """Return the headers a client presents after authenticating successfully."""
        return {
            SUBJECT_HEADER: subject,
            ROLES_HEADER: roles,
            SIGNATURE_HEADER: self.sign(subject, roles),
        }


def _roles(raw: str) -> frozenset[str]:
    return frozenset(role.strip() for role in raw.split(",") if role.strip())
