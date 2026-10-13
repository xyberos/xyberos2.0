"""Generate the JSON Schema an editor uses to complete and validate ``xyberos.toml``.

The schema is *generated* from the ``Settings`` dataclasses rather than written beside them, so a
field that changes and a schema that does not is impossible: `tests/test_config_schema.py` compares
the shipped file with what this module produces and fails when they drift. That is the whole reason
the file can be handed to an editor with no extension to install — it is the same object the runtime
reads, described.

Two channels are deliberately described differently, which is the distinction
`docs/implementation.md` records: a plugin's ``config_type`` is a dataclass, so its section gets
real properties and ``additionalProperties: false``; the ``[ai.<name>]`` sections are opaque to
core, so the schema says "an object" and stops. A schema that guessed at keys core does not know
would validate more loosely than it reads.
"""

from __future__ import annotations

import dataclasses
import json
import types
import typing
from collections.abc import Mapping
from pathlib import Path

from xyberos.config import AppSettings

__all__ = [
    "SCHEMA_DRAFT",
    "SCHEMA_ID",
    "SCHEMA_PATH",
    "settings_schema",
    "write_schema",
]

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID = "https://docs.xyberos.com/schema/xyberos-config-1.json"
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "config.schema.json"
"""Where the generated schema ships: inside the package, so the wheel carries it."""

_SIMPLE_TYPES: dict[object, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def settings_schema(
    *,
    plugin_sections: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return the JSON Schema for ``xyberos.toml``.

    ``plugin_sections`` maps a plugin's name to its ``config_type``. Passing it produces the schema
    an editor wants for *this* application, with each declared plugin's section typed; leaving it
    out produces the schema that ships, where the plugin table is described but its sections are
    not.
    """
    plugins: dict[str, object] = {
        "type": "object",
        "description": (
            "One table per plugin, keyed by the plugin's name. Each plugin validates its own "
            "section against the config_type it declares, and rejects unknown keys."
        ),
        "additionalProperties": {"type": "object"},
    }
    properties: dict[str, object] = {
        "schema_version": {
            "type": "integer",
            "description": (
                "The configuration format version. Required from the first public format."
            ),
        },
        "app": _dataclass_schema(AppSettings, description="Settings owned by the runtime."),
        "plugins": plugins,
        "ai": {
            "type": "object",
            "description": (
                "One table per AI provider. Core validates the shape and leaves every AI "
                "concept to the adapter that reads it, so this schema describes no keys."
            ),
            "additionalProperties": {"type": "object"},
        },
    }

    if plugin_sections:
        plugins["properties"] = {
            name: _dataclass_schema(config_type, description=f"Settings for the {name!r} plugin.")
            for name, config_type in sorted(plugin_sections.items())
        }

    return {
        "$schema": SCHEMA_DRAFT,
        "$id": SCHEMA_ID,
        "title": "xyberos.toml",
        "description": (
            "Configuration for a Xyberos application. Generated from the Settings dataclasses by "
            "`xyberos check --schema`; do not edit it by hand."
        ),
        "type": "object",
        "additionalProperties": False,
        "properties": properties,
    }


def write_schema(path: Path = SCHEMA_PATH) -> Path:
    """Write the shipped schema to ``path`` and return it."""
    rendered = json.dumps(settings_schema(), indent=2, sort_keys=True)
    path.write_text(rendered + "\n", encoding="utf-8")
    return path


def _dataclass_schema(config_type: object, *, description: str) -> dict[str, object]:
    """Return the schema for one dataclass, or fail loudly if it cannot be described.

    Failing rather than falling back to "an object" is the point: a ``Settings`` field whose type
    this generator does not understand would otherwise ship as an editor that silently completes
    nothing.
    """
    if not dataclasses.is_dataclass(config_type):
        raise TypeError(f"{config_type!r} is not a dataclass, so it cannot be described")
    hints = typing.get_type_hints(config_type)
    properties: dict[str, object] = {}
    required: list[str] = []
    for field in dataclasses.fields(config_type):
        properties[field.name] = _field_schema(hints[field.name], location=field.name)
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            required.append(field.name)
    return {
        "type": "object",
        "description": description,
        "additionalProperties": False,
        "properties": properties,
        **({"required": sorted(required)} if required else {}),
    }


def _field_schema(annotation: object, *, location: str) -> dict[str, object]:
    """Return the schema for one field's annotation, unwrapping ``X | None``."""
    optional, inner = _unwrap_optional(annotation)
    if inner in _SIMPLE_TYPES:
        described: dict[str, object] = {"type": _SIMPLE_TYPES[inner]}
    elif dataclasses.is_dataclass(inner):
        described = _dataclass_schema(inner, description=f"The {location} table.")
    elif typing.get_origin(inner) is Mapping or inner is Mapping:
        described = {
            "type": "object",
            "additionalProperties": {"type": "object"},
        }
    else:
        raise TypeError(
            f"the setting {location!r} has a type this schema cannot describe: {inner!r}"
        )
    if optional:
        # Every branch above sets one type name, so an optional field is that name plus null.
        described["type"] = [described["type"], "null"]
    return described


def _unwrap_optional(annotation: object) -> tuple[bool, object]:
    origin = typing.get_origin(annotation)
    if origin is types.UnionType or origin is typing.Union:
        arguments = typing.get_args(annotation)
        if len(arguments) == 2 and type(None) in arguments:
            inner = arguments[0] if arguments[1] is type(None) else arguments[1]
            return True, inner
    return False, annotation
