"""The configuration schema: generated, shipped, and kept in step with the dataclasses.

An editor that validates `xyberos.toml` is only useful if what it validates is what the runtime
reads. So this file checks three things: the shipped file is exactly what the generator produces,
the shapes agree with the loader's behaviour rather than merely resembling it, and a field added to
a `Settings` dataclass without regenerating the file fails here instead of in somebody's editor.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from xyberos.cli.schema import SCHEMA_DRAFT, SCHEMA_PATH, settings_schema
from xyberos.config import AppSettings, Settings


@dataclasses.dataclass(frozen=True)
class MetricsConfig:
    prefix: str = "xyberos"
    enabled: bool = True


@dataclasses.dataclass(frozen=True)
class OddConfig:
    anything: object = None


def test_the_shipped_file_is_exactly_what_the_generator_produces() -> None:
    shipped = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert shipped == settings_schema()


def test_the_schema_ships_inside_the_package_so_the_wheel_carries_it() -> None:
    assert SCHEMA_PATH.parent.name == "xyberos"
    assert SCHEMA_PATH.name == "config.schema.json"
    assert SCHEMA_PATH.is_file()


def test_the_schema_names_its_draft_and_an_id_a_tool_can_resolve() -> None:
    schema = settings_schema()

    assert schema["$schema"] == SCHEMA_DRAFT
    assert str(schema["$id"]).startswith("https://")


def test_the_root_describes_exactly_the_keys_the_loader_accepts() -> None:
    """Four root keys, and unknown ones rejected — which is what `_reject_unknown_keys` does."""
    schema = settings_schema()

    assert set(schema["properties"]) == {"schema_version", "app", "plugins", "ai"}
    assert schema["additionalProperties"] is False


def test_the_app_table_describes_every_field_the_dataclass_declares() -> None:
    """The drift check: add an `AppSettings` field and this fails until the file is regenerated."""
    described = settings_schema()["properties"]["app"]["properties"]
    declared = {field.name for field in dataclasses.fields(AppSettings)}

    assert set(described) == declared


def test_an_optional_number_is_described_as_nullable() -> None:
    app = settings_schema()["properties"]["app"]["properties"]

    assert app["shutdown_timeout"]["type"] == ["number", "null"]
    assert app["debug"]["type"] == "boolean"


def test_the_settings_table_is_the_only_one_that_carries_a_schema_version() -> None:
    """`Settings.schema_version` is what the loader validates first, so it is described here."""
    assert settings_schema()["properties"]["schema_version"]["type"] == "integer"
    fields = {field.name for field in dataclasses.fields(Settings)}
    assert "schema_version" in fields


def test_a_plugin_section_is_typed_from_the_config_type_it_declares() -> None:
    schema = settings_schema(plugin_sections={"metrics": MetricsConfig})
    section = schema["properties"]["plugins"]["properties"]["metrics"]

    assert section["additionalProperties"] is False
    assert set(section["properties"]) == {"prefix", "enabled"}
    assert section["properties"]["enabled"]["type"] == "boolean"


def test_without_an_application_the_plugin_table_is_described_but_not_enumerated() -> None:
    plugins = settings_schema()["properties"]["plugins"]

    assert "properties" not in plugins
    assert plugins["additionalProperties"] == {"type": "object"}


def test_the_ai_channel_is_left_to_the_adapter_that_reads_it() -> None:
    """Core validates the shape and knows no keys, so the schema must not pretend otherwise."""
    ai = settings_schema()["properties"]["ai"]

    assert "properties" not in ai
    assert ai["additionalProperties"] == {"type": "object"}


def test_a_setting_the_generator_cannot_describe_fails_loudly() -> None:
    """An editor that silently completes nothing is worse than a build that stops."""
    with pytest.raises(TypeError, match="cannot describe"):
        settings_schema(plugin_sections={"odd": OddConfig})
