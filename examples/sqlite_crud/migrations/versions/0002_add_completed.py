"""add the completed flag using SQLite batch mode

SQLite cannot add a NOT NULL column in place, so this revision uses ``batch_alter_table``, which
rebuilds the table. The migration is exercised by the test suite so the rebuild behavior is proven
before it reaches production data.

Revision ID: 0002_add_completed
Revises: 0001_create_items
Create Date: 2026-10-10

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_completed"
down_revision = "0001_create_items"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.add_column(
            sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("0"))
        )


def downgrade() -> None:
    with op.batch_alter_table("items") as batch:
        batch.drop_column("completed")
