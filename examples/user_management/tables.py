"""SQLAlchemy Core table definitions owned by the application, not the framework."""

from __future__ import annotations

from sqlalchemy import Boolean, Column, Integer, MetaData, String, Table, text

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(320), nullable=False, unique=True),
    Column("display_name", String(200), nullable=False),
    Column("enabled", Boolean, nullable=False, server_default=text("1")),
    Column("external_subject", String(200), nullable=True, unique=True),
)
