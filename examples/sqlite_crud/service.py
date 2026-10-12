"""The item service: business rules and transaction boundaries, no HTTP types."""

from __future__ import annotations

from typing import Annotated

from sqlalchemy import delete, insert, select, update

from sqlite_crud.errors import ItemNotFoundError, ItemValidationError
from sqlite_crud.tables import items
from xyberos import Inject
from xyberos.database import DatabaseProvider

MAX_NAME_LENGTH = 200


class ItemService:
    """Owns item rules and keeps every write inside one short transaction."""

    def __init__(self, database: Annotated[DatabaseProvider, Inject()]) -> None:
        self._database = database

    async def list_items(self) -> list[dict[str, object]]:
        async with self._database.transaction() as connection:
            rows = (await connection.execute(select(items).order_by(items.c.id))).mappings().all()
        return [dict(row) for row in rows]

    async def get_item(self, item_id: int) -> dict[str, object]:
        async with self._database.transaction() as connection:
            row = (
                (await connection.execute(select(items).where(items.c.id == item_id)))
                .mappings()
                .first()
            )
        if row is None:
            raise ItemNotFoundError(item_id)
        return dict(row)

    async def create_item(self, name: object) -> dict[str, object]:
        validated = _validated_name(name)
        async with self._database.transaction() as connection:
            result = await connection.execute(insert(items).values(name=validated, completed=False))
            inserted = result.inserted_primary_key
            if inserted is None:
                # SQLAlchemy types this as optional, and an insert with a generated key reports one.
                raise AssertionError("the insert reported no primary key")
            item_id = int(inserted[0])
            row = (
                (await connection.execute(select(items).where(items.c.id == item_id)))
                .mappings()
                .one()
            )
        return dict(row)

    async def rename_item(self, item_id: int, name: object) -> dict[str, object]:
        validated = _validated_name(name)
        async with self._database.transaction() as connection:
            result = await connection.execute(
                update(items).where(items.c.id == item_id).values(name=validated)
            )
            if result.rowcount == 0:
                raise ItemNotFoundError(item_id)
            row = (
                (await connection.execute(select(items).where(items.c.id == item_id)))
                .mappings()
                .one()
            )
        return dict(row)

    async def set_completed(self, item_id: int, completed: object) -> dict[str, object]:
        if not isinstance(completed, bool):
            raise ItemValidationError("completed must be a boolean")
        async with self._database.transaction() as connection:
            result = await connection.execute(
                update(items).where(items.c.id == item_id).values(completed=completed)
            )
            if result.rowcount == 0:
                raise ItemNotFoundError(item_id)
            row = (
                (await connection.execute(select(items).where(items.c.id == item_id)))
                .mappings()
                .one()
            )
        return dict(row)

    async def delete_item(self, item_id: int) -> None:
        async with self._database.transaction() as connection:
            result = await connection.execute(delete(items).where(items.c.id == item_id))
            if result.rowcount == 0:
                raise ItemNotFoundError(item_id)


def _validated_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ItemValidationError("name must be a non-empty string")
    normalized = name.strip()
    if len(normalized) > MAX_NAME_LENGTH:
        raise ItemValidationError(f"name must be at most {MAX_NAME_LENGTH} characters")
    return normalized
