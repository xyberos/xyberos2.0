"""SQLAlchemy Core table definitions owned by the application, not the framework."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, text

metadata = MetaData()

items = Table(
    "items",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(200), nullable=False),
    Column("completed", Boolean, nullable=False, server_default=text("0")),
)
