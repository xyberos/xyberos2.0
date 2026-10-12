"""create the orders table

Revision ID: 0001_create_orders
Revises:
Create Date: 2026-10-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_create_orders"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("total", sa.Float(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("orders")
