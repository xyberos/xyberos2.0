"""Alembic environment for the orders application.

The database URL arrives from the caller — application code, or the `xyberos migrate` command — so
no URL is committed here. The application's ``metadata`` is the target for autogenerate, which is
why the package is made importable before it is read.

Alembic's own engine is synchronous, so the URL passed in is the synchronous form of the one the
application uses (``SqliteSettings.sync_url`` for SQLite).
"""

from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make the application importable when Alembic runs from any working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from learn_production.orders_tables import metadata  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = metadata


def run_migrations_offline() -> None:
    """Emit SQL for the migration without connecting to a database."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply the migration against a live database."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
