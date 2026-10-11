"""The Alembic configuration passes a URL through, and passes it through intact.

A database URL is data: a password is percent-encoded as a matter of course, and a SQLite path may
contain a percent sign. Alembic reads its configuration through configparser, which treats a bare
``%`` as the start of a substitution — so the value has to be escaped on the way in, and this file
is the evidence that it comes back unchanged rather than corrupted or quoted in an exception.
"""

from __future__ import annotations

import pytest

from xyberos.database import alembic_config

PERCENT_URLS = [
    "postgresql://user:S3cr3t%40pw@db.example:5432/app",
    "postgresql://user:100%25@db.example:5432/app",
    "sqlite:///var/100%.db",
    "sqlite+aiosqlite:///%TEMP%/app.db",
    "%",
]


@pytest.mark.parametrize("url", PERCENT_URLS)
def test_a_url_containing_a_percent_sign_survives_the_configuration(url: str) -> None:
    config = alembic_config("migrations", url=url)

    assert config.get_main_option("sqlalchemy.url") == url


@pytest.mark.parametrize("url", PERCENT_URLS)
def test_the_section_alembic_reads_carries_the_same_url(url: str) -> None:
    """``get_section`` is a second path to the same value, and Alembic's env templates use it."""
    config = alembic_config("migrations", url=url)

    section = config.get_section(config.config_ini_section)

    assert section is not None
    assert section["sqlalchemy.url"] == url


def test_the_script_location_is_still_set() -> None:
    config = alembic_config("migrations", url="sqlite:///app.db")

    assert config.get_main_option("script_location") == "migrations"
