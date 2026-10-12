"""The support desk's schema: ordinary rows, because an audit trail is data and not a feature.

Nothing in the package knows what a ticket is. Every table here is the application's, which is what
lets the path assert things the framework cannot: that sending a reply needs an approval row, and
that a model cannot change a ticket because no tool it may call writes one.
"""

from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, text

metadata = MetaData()

tickets = Table(
    "tickets",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(80), nullable=False),
    Column("requester", String(200), nullable=False),
    Column("subject", String(200), nullable=False),
    Column("body", String(4000), nullable=False),
    Column("state", String(40), nullable=False, server_default=text("'new'")),
    Column("category", String(40), nullable=True),
    Column("confidence", String(20), nullable=True),
)

#: A draft the model produced. It has no send path, and the approval columns are the only way a body
#: becomes one someone sent: `body` is what the model wrote, `approved_body` is what a person put
#: their name to, and `approved_by` is who.
suggested_replies = Table(
    "suggested_replies",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("ticket_id", Integer, nullable=False),
    Column("body", String(4000), nullable=False),
    Column("model", String(120), nullable=False),
    Column("approved_by", String(200), nullable=True),
    Column("approved_body", String(4000), nullable=True),
    Column("approved_at", String(40), nullable=True),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(80), nullable=False),
    Column("ticket_id", Integer, nullable=False),
    Column("actor", String(200), nullable=False),
    Column("action", String(60), nullable=False),
    Column("detail", String(1000), nullable=False, server_default=text("''")),
    Column("recorded_at", String(40), nullable=False),
)

#: A vector is stored as JSON in a text column because the deployment is SQLite and the
#: deterministic provider returns four numbers. A real one stores them in a vector store and queries
#: it with these rows; that store is the part of retrieval the package does not ship.
passages = Table(
    "passages",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source", String(120), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("text", String(2000), nullable=False),
    Column("vector", String(4000), nullable=False),
)

usage_events = Table(
    "usage_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(80), nullable=False),
    Column("ticket_id", Integer, nullable=True),
    Column("step", String(60), nullable=False),
    Column("model", String(120), nullable=False),
    Column("input_tokens", Integer, nullable=False, server_default=text("0")),
    Column("output_tokens", Integer, nullable=False, server_default=text("0")),
    Column("outcome", String(40), nullable=False, server_default=text("'pending'")),
    Column("recorded_at", String(40), nullable=False),
)

#: What the mailer wrote. A suggestion that was never approved leaves this table empty, which the
#: path asserts rather than describes.
outbox = Table(
    "outbox",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(80), nullable=False),
    Column("ticket_id", Integer, nullable=False),
    Column("recipient", String(200), nullable=False),
    Column("body", String(4000), nullable=False),
    Column("sent_at", String(40), nullable=False),
)

jobs = Table(
    "jobs",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("tenant", String(80), nullable=False),
    Column("ticket_id", Integer, nullable=False),
    Column("submitted_by", String(200), nullable=False),
    Column("state", String(40), nullable=False, server_default=text("'queued'")),
    Column("detail", String(1000), nullable=False, server_default=text("''")),
)
