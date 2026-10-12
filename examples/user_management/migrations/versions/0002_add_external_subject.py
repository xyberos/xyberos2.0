"""link users to the subject an identity provider verifies

The subject is a separate column rather than the email address, because the two change for different
reasons: an email address can be changed by the person who owns it, while a subject is what the
identity provider will keep asserting. A local account linked by email stops being reachable the
first time somebody's address changes upstream.

The column is nullable and unique: most rows may have no link yet, and no two accounts may claim the
same subject.

Revision ID: 0002_add_external_subject
Revises: 0001_create_users
Create Date: 2026-10-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_add_external_subject"
down_revision = "0001_create_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("external_subject", sa.String(length=200), nullable=True))
        batch.create_unique_constraint("uq_users_external_subject", ["external_subject"])


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_external_subject", type_="unique")
        batch.drop_column("external_subject")
