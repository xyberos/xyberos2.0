"""The user service: business rules and transaction boundaries, no HTTP types."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated

from sqlalchemy import delete, func, insert, select, update

from user_management.errors import (
    AccountAlreadyLinkedError,
    AccountNotLinkedError,
    DuplicateEmailError,
    UserNotFoundError,
    UserValidationError,
)
from user_management.identity import Principal
from user_management.tables import users
from xyberos import Inject
from xyberos.database import DatabaseProvider

MAX_EMAIL_LENGTH = 320
MAX_DISPLAY_NAME_LENGTH = 200
DEFAULT_LIMIT = 20
MAX_LIMIT = 100
ALLOWED_FIELDS = ("email", "display_name", "enabled")
#: What a user may change about themselves. Everything else is somebody else's decision.
SELF_FIELDS = ("display_name",)


class UserService:
    """Owns user rules and keeps every write inside one short transaction."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def create_user(
        self,
        email: object,
        display_name: object,
        *,
        external_subject: str | None = None,
    ) -> dict[str, object]:
        """Insert one user, or raise because the input is wrong or the email is taken.

        ``external_subject`` links the new account to a verified principal. Both checks happen in
        the same transaction as the insert, and the order of the three refusals is deliberate: a
        conflict about the request's target first, then the payload, then a value it names.
        """
        async with self._database.transaction() as connection:
            if external_subject is not None:
                linked = (
                    await connection.execute(
                        select(users.c.id).where(users.c.external_subject == external_subject)
                    )
                ).first()
                if linked is not None:
                    raise AccountAlreadyLinkedError(external_subject)
            normalized_email = _validated_email(email)
            normalized_name = _validated_display_name(display_name)
            taken = (
                await connection.execute(
                    select(users.c.id).where(users.c.email == normalized_email)
                )
            ).first()
            if taken is not None:
                raise DuplicateEmailError(normalized_email)
            result = await connection.execute(
                insert(users).values(
                    email=normalized_email,
                    display_name=normalized_name,
                    external_subject=external_subject,
                )
            )
            user_id = int(result.inserted_primary_key[0])
            row = (
                (await connection.execute(select(users).where(users.c.id == user_id)))
                .mappings()
                .one()
            )
        return dict(row)

    async def list_users(self, *, limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict[str, object]:
        """Return one page of users, newest row last, with the size of the whole table."""
        page_limit = _validated_limit(limit)
        page_offset = _validated_offset(offset)
        statement = select(users).order_by(users.c.id).limit(page_limit).offset(page_offset)
        async with self._database.transaction() as connection:
            total = int(
                (await connection.execute(select(func.count()).select_from(users))).scalar_one()
            )
            rows = (await connection.execute(statement)).mappings().all()
        return {
            "items": [dict(row) for row in rows],
            "total": total,
            "limit": page_limit,
            "offset": page_offset,
        }

    async def get_user(self, user_id: int) -> dict[str, object]:
        """Return one user, or raise because there is no such user."""
        async with self._database.transaction() as connection:
            row = (
                (await connection.execute(select(users).where(users.c.id == user_id)))
                .mappings()
                .first()
            )
        if row is None:
            raise UserNotFoundError(user_id)
        return dict(row)

    async def update_user(self, user_id: int, changes: Mapping[str, object]) -> dict[str, object]:
        """Apply what the client sent, and nothing else, to one existing user."""
        values = _validated_changes(changes)
        async with self._database.transaction() as connection:
            exists = (
                await connection.execute(select(users.c.id).where(users.c.id == user_id))
            ).first()
            if exists is None:
                raise UserNotFoundError(user_id)
            if "email" in values:
                taken = (
                    await connection.execute(
                        select(users.c.id).where(
                            users.c.email == values["email"], users.c.id != user_id
                        )
                    )
                ).first()
                if taken is not None:
                    raise DuplicateEmailError(str(values["email"]))
            await connection.execute(update(users).where(users.c.id == user_id).values(**values))
            row = (
                (await connection.execute(select(users).where(users.c.id == user_id)))
                .mappings()
                .one()
            )
        return dict(row)

    async def delete_user(self, user_id: int) -> None:
        """Delete one user, or raise because there is no such user."""
        async with self._database.transaction() as connection:
            result = await connection.execute(delete(users).where(users.c.id == user_id))
            if result.rowcount == 0:
                raise UserNotFoundError(user_id)

    async def find_own_user(self, principal: Principal) -> dict[str, object]:
        """Return the account a verified principal belongs to, or raise because there is none.

        The subject comes from the principal and nowhere else: there is no user id in this
        signature, so a request cannot ask for somebody else's account by naming it.
        """
        async with self._database.transaction() as connection:
            row = (
                (
                    await connection.execute(
                        select(users).where(users.c.external_subject == principal.subject)
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            raise AccountNotLinkedError(principal.subject)
        return dict(row)

    async def update_own_profile(
        self, principal: Principal, changes: Mapping[str, object]
    ) -> dict[str, object]:
        """Change what a user may change about themselves, and nothing else."""
        unknown = sorted(set(changes) - set(SELF_FIELDS))
        if unknown:
            raise UserValidationError(f"unknown field: {unknown[0]}")
        if not changes:
            raise UserValidationError(f"provide at least one of {', '.join(SELF_FIELDS)}")
        display_name = _validated_display_name(changes["display_name"])
        async with self._database.transaction() as connection:
            exists = (
                await connection.execute(
                    select(users.c.id).where(users.c.external_subject == principal.subject)
                )
            ).first()
            if exists is None:
                raise AccountNotLinkedError(principal.subject)
            await connection.execute(
                update(users)
                .where(users.c.external_subject == principal.subject)
                .values(display_name=display_name)
            )
            row = (
                (
                    await connection.execute(
                        select(users).where(users.c.external_subject == principal.subject)
                    )
                )
                .mappings()
                .one()
            )
        return dict(row)


def _validated_changes(changes: Mapping[str, object]) -> dict[str, object]:
    """Keep the fields the client may change, and refuse the ones it may not name."""
    unknown = sorted(set(changes) - set(ALLOWED_FIELDS))
    if unknown:
        raise UserValidationError(f"unknown field: {unknown[0]}")
    values: dict[str, object] = {}
    if "email" in changes:
        values["email"] = _validated_email(changes["email"])
    if "display_name" in changes:
        values["display_name"] = _validated_display_name(changes["display_name"])
    if "enabled" in changes:
        values["enabled"] = _validated_flag(changes["enabled"])
    if not values:
        raise UserValidationError(f"provide at least one of {', '.join(ALLOWED_FIELDS)}")
    return values


def _validated_flag(enabled: object) -> bool:
    if not isinstance(enabled, bool):
        raise UserValidationError("enabled must be a boolean")
    return enabled


def _validated_email(email: object) -> str:
    if not isinstance(email, str) or not email.strip():
        raise UserValidationError("email must be a non-empty string")
    normalized = email.strip().lower()
    local, separator, domain = normalized.partition("@")
    if not separator or not local or "." not in domain.strip("."):
        raise UserValidationError("email must look like name@example.com")
    if len(normalized) > MAX_EMAIL_LENGTH:
        raise UserValidationError(f"email must be at most {MAX_EMAIL_LENGTH} characters")
    return normalized


def _validated_display_name(display_name: object) -> str:
    if not isinstance(display_name, str) or not display_name.strip():
        raise UserValidationError("display_name must be a non-empty string")
    collapsed = " ".join(display_name.split())
    if len(collapsed) > MAX_DISPLAY_NAME_LENGTH:
        raise UserValidationError(
            f"display_name must be at most {MAX_DISPLAY_NAME_LENGTH} characters"
        )
    return collapsed


def _validated_limit(limit: int) -> int:
    if not 1 <= limit <= MAX_LIMIT:
        raise UserValidationError(f"limit must be between 1 and {MAX_LIMIT}")
    return limit


def _validated_offset(offset: int) -> int:
    if offset < 0:
        raise UserValidationError("offset must not be negative")
    return offset
