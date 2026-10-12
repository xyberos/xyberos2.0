"""The mailer: a transactional outbox, so a sent reply and the state that says so commit together.

A real deployment hands the row to an SMTP relay or a provider's API from a small worker. What
matters here is the shape, and the shape is the point: the row is written inside the caller's
transaction, so either the reply is sent *and* the ticket says ``replied``, or neither happened.
The alternative — send first, record after — is a reply nobody can account for when the second
step fails.

A suggestion that was never approved leaves this table empty, which is what the path asserts.
"""

from __future__ import annotations

from typing import Annotated

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from support_desk.clock import utc_now
from support_desk.tables import outbox
from xyberos import Inject
from xyberos.database import DatabaseProvider


class Mailer:
    """Delivers a reply by recording it, so a send is a row and not a side effect nobody can see."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def deliver(
        self,
        connection: AsyncConnection,
        *,
        tenant: str,
        ticket_id: int,
        recipient: str,
        body: str,
    ) -> int:
        """Write one approved body to the outbox inside the caller's transaction."""
        result = await connection.execute(
            insert(outbox).values(
                tenant=tenant,
                ticket_id=ticket_id,
                recipient=recipient,
                body=body,
                sent_at=utc_now(),
            )
        )
        inserted = result.inserted_primary_key
        if inserted is None:
            raise AssertionError("the insert reported no primary key")
        return int(inserted[0])

    async def messages(self, *, tenant: str, ticket_id: int) -> list[dict[str, object]]:
        """Return what was sent for one ticket, oldest first."""
        statement = (
            select(outbox)
            .where(outbox.c.tenant == tenant, outbox.c.ticket_id == ticket_id)
            .order_by(outbox.c.id)
        )
        async with self._database.transaction() as connection:
            rows = (await connection.execute(statement)).mappings().all()
        return [dict(row) for row in rows]

    async def count(self) -> int:
        """Return how many replies have been sent at all, which is the assertion that matters."""
        async with self._database.transaction() as connection:
            return int(
                (await connection.execute(select(func.count()).select_from(outbox))).scalar_one()
            )
