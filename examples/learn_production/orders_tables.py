"""The tables this application owns, as SQLAlchemy Core metadata.

The application queries these tables through the database provider's transactions; the migration
below creates them. Both read the same definition of the table names and columns, which is the part
worth keeping in one place even when the DDL is written out.
"""

from __future__ import annotations

from sqlalchemy import Column, Float, Integer, MetaData, Table

metadata = MetaData()

orders = Table(
    "orders",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("total", Float, nullable=False),
)
