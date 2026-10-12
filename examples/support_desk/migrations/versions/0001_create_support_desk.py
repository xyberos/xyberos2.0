"""create the support desk schema

Revision ID: 0001_create_support_desk
Revises:
Create Date: 2026-10-12

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_create_support_desk"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(length=80), nullable=False),
        sa.Column("requester", sa.String(length=200), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("state", sa.String(length=40), nullable=False, server_default=sa.text("'new'")),
        sa.Column("category", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.String(length=20), nullable=True),
    )
    op.create_table(
        "suggested_replies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("approved_by", sa.String(length=200), nullable=True),
        sa.Column("approved_body", sa.String(length=4000), nullable=True),
        sa.Column("approved_at", sa.String(length=40), nullable=True),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(length=80), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("actor", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False),
        sa.Column("detail", sa.String(length=1000), nullable=False, server_default=sa.text("''")),
        sa.Column("recorded_at", sa.String(length=40), nullable=False),
    )
    op.create_table(
        "passages",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.String(length=2000), nullable=False),
        sa.Column("vector", sa.String(length=4000), nullable=False),
    )
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(length=80), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=True),
        sa.Column("step", sa.String(length=60), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "outcome", sa.String(length=40), nullable=False, server_default=sa.text("'pending'")
        ),
        sa.Column("recorded_at", sa.String(length=40), nullable=False),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(length=80), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("recipient", sa.String(length=200), nullable=False),
        sa.Column("body", sa.String(length=4000), nullable=False),
        sa.Column("sent_at", sa.String(length=40), nullable=False),
    )
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant", sa.String(length=80), nullable=False),
        sa.Column("ticket_id", sa.Integer(), nullable=False),
        sa.Column("submitted_by", sa.String(length=200), nullable=False),
        sa.Column(
            "state", sa.String(length=40), nullable=False, server_default=sa.text("'queued'")
        ),
        sa.Column("detail", sa.String(length=1000), nullable=False, server_default=sa.text("''")),
    )


def downgrade() -> None:
    op.drop_table("jobs")
    op.drop_table("outbox")
    op.drop_table("usage_events")
    op.drop_table("passages")
    op.drop_table("audit_events")
    op.drop_table("suggested_replies")
    op.drop_table("tickets")
