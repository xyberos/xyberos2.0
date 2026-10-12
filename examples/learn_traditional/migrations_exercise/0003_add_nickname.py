"""add a nickname to users, rebuilding the table in SQLite batch mode

SQLite cannot alter a column in place, so ``batch_alter_table`` rebuilds the table: it creates a new
one, copies the rows into it, and swaps it in. That is why this revision is safe to run against a
database that already holds users.

``down_revision`` is the current head — the last revision in the directory, which this file follows.
A migration that names the wrong predecessor is either a no-op or a branch, and Alembic refuses a
directory with two heads rather than guessing.

Revision ID: 0003_add_nickname
Revises: 0002_add_external_subject
Create Date: 2026-10-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_add_nickname"
down_revision = "0002_add_external_subject"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("nickname", sa.String(length=100), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("nickname")
