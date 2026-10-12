"""create the users table

Revision ID: 0001_create_users
Revises:
Create Date: 2026-10-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_create_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )


def downgrade() -> None:
    op.drop_table("users")
