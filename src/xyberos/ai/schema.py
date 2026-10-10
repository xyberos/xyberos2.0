"""A closed JSON Schema subset for structured output and tool arguments.

Xyberos validates structured output itself instead of depending on a schema library. The subset is
deliberately small and *closed*: an unsupported keyword is rejected when a schema is declared rather
than ignored at validation time, so a schema can never validate more loosely than it reads.

Supported keywords: ``type``, ``properties``, ``required``, ``additionalProperties``, ``items``,
``enum``, ``minimum``, ``maximum``, ``minLength``, ``maxLength``, ``minItems``, ``maxItems``, plus
the documentation-only ``description``, ``title``, ``default``, ``examples``, and ``format``.

Supported types: ``object``, ``array``, ``string``, ``number``, ``integer``, ``boolean``, ``null``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from xyberos.errors import AIRequestError, AISchemaError

_SCHEMA_KEYWORDS = frozenset(
    {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
        "minimum",
        "maximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "description",
        "title",
        "default",
        "examples",
        "format",
    }
)
_ANNOTATION_KEYWORDS = frozenset({"description", "title", "default", "examples", "format"})
_SUPPORTED_TYPES = (
    "object",
    "array",
    "string",
    "number",
    "integer",
    "boolean",
    "null",
)
_LENGTH_KEYWORDS = ("minLength", "maxLength")
_COUNT_KEYWORDS = ("minItems", "maxItems")
_BOUND_KEYWORDS = ("minimum", "maximum")


def check_schema(schema: object, *, location: str) -> None:
    """Raise :class:`~xyberos.errors.AIRequestError` unless ``schema`` is usable as declared."""
    _check_node(schema, location=location, path="$")


def validate_payload(
    payload: object, schema: Mapping[str, object], *, location: str = "payload"
) -> object:
    """Validate ``payload`` against ``schema`` and return it unchanged.

    Raises :class:`~xyberos.errors.AISchemaError` naming the first failing location, or
    :class:`~xyberos.errors.AIRequestError` if the schema itself is unusable.
    """
    check_schema(schema, location=location)
    _validate_node(payload, schema, location=location, path="$")
    return payload


def describe_schema(schema: Mapping[str, object]) -> str:
    """Return a short human-readable summary of a schema, for prompts and diagnostics."""
    declared = schema.get("type")
    if isinstance(declared, str):
        return declared
    if isinstance(declared, Sequence) and not isinstance(declared, str):
        return " or ".join(str(item) for item in declared)
    if "properties" in schema:
        return "object"
    return "any"


def _check_node(schema: object, *, location: str, path: str) -> None:
    if not isinstance(schema, Mapping):
        raise AIRequestError(f"{location} at {path} must be an object, not {_describe(schema)}")
    unknown = sorted(set(schema) - _SCHEMA_KEYWORDS)
    if unknown:
        supported = ", ".join(sorted(_SCHEMA_KEYWORDS - _ANNOTATION_KEYWORDS))
        raise AIRequestError(
            f"{location} at {path} uses unsupported keyword(s): {', '.join(unknown)}; "
            f"supported keywords are: {supported}"
        )
    _check_type_keyword(schema.get("type"), location=location, path=path)
    _check_enum_keyword(schema.get("enum"), location=location, path=path)
    _check_additional_properties(schema.get("additionalProperties"), location=location, path=path)
    for keyword in (*_LENGTH_KEYWORDS, *_COUNT_KEYWORDS):
        _check_non_negative_int(schema.get(keyword), keyword, location=location, path=path)
    for keyword in _BOUND_KEYWORDS:
        _check_number(schema.get(keyword), keyword, location=location, path=path)
    properties = schema.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            raise AIRequestError(f"{location} at {path}.properties must be an object")
        for name, child in properties.items():
            if not isinstance(name, str) or not name:
                raise AIRequestError(f"{location} at {path}.properties needs non-empty names")
            _check_node(child, location=location, path=f"{path}.{name}")
    required = schema.get("required")
    if required is not None:
        if isinstance(required, str) or not isinstance(required, Sequence):
            raise AIRequestError(f"{location} at {path}.required must be an array of names")
        for name in required:
            if not isinstance(name, str) or not name:
                raise AIRequestError(f"{location} at {path}.required must name properties")
        if isinstance(properties, Mapping):
            undeclared = sorted(set(required) - set(properties))
            if undeclared:
                raise AIRequestError(
                    f"{location} at {path}.required names undeclared propert(ies): "
                    f"{', '.join(undeclared)}"
                )
    items = schema.get("items")
    if items is not None:
        _check_node(items, location=location, path=f"{path}[]")


def _check_type_keyword(value: object, *, location: str, path: str) -> None:
    if value is None:
        return
    candidates: Sequence[object]
    if isinstance(value, str):
        candidates = (value,)
    elif isinstance(value, Sequence):
        candidates = value
    else:
        raise AIRequestError(f"{location} at {path}.type must be a name or an array of names")
    for candidate in candidates:
        if candidate not in _SUPPORTED_TYPES:
            supported = ", ".join(_SUPPORTED_TYPES)
            raise AIRequestError(
                f"{location} at {path}.type uses unsupported type {candidate!r}; "
                f"supported types are: {supported}"
            )


def _check_enum_keyword(value: object, *, location: str, path: str) -> None:
    if value is None:
        return
    if isinstance(value, str) or not isinstance(value, Sequence) or not value:
        raise AIRequestError(f"{location} at {path}.enum must be a non-empty array")


def _check_additional_properties(value: object, *, location: str, path: str) -> None:
    if value is not None and not isinstance(value, bool):
        raise AIRequestError(f"{location} at {path}.additionalProperties must be true or false")


def _check_non_negative_int(value: object, keyword: str, *, location: str, path: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AIRequestError(f"{location} at {path}.{keyword} must be a non-negative integer")


def _check_number(value: object, keyword: str, *, location: str, path: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AIRequestError(f"{location} at {path}.{keyword} must be a number")


def _validate_node(
    value: object, schema: Mapping[str, object], *, location: str, path: str
) -> None:
    if not _matches_declared_types(value, schema.get("type")):
        raise AISchemaError(
            f"{location} at {path} must be {_described_types(schema.get('type'))}, "
            f"got {_describe(value)}"
        )
    _validate_enum(value, schema, location=location, path=path)
    _validate_bounds(value, schema, location=location, path=path)
    items = schema.get("items")
    if isinstance(value, Mapping):
        _validate_object(value, schema, location=location, path=path)
    elif isinstance(value, (list, tuple)) and isinstance(items, Mapping):
        for index, item in enumerate(value):
            _validate_node(item, items, location=location, path=f"{path}[{index}]")


def _matches_declared_types(value: object, declared: object) -> bool:
    if declared is None:
        return True
    if isinstance(declared, str):
        return _matches_type(value, declared)
    return any(_matches_type(value, candidate) for candidate in _sequence(declared))


def _matches_type(value: object, expected: object) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, (list, tuple))
    if expected == "object":
        return isinstance(value, Mapping)
    return False


def _validate_enum(
    value: object, schema: Mapping[str, object], *, location: str, path: str
) -> None:
    allowed = _sequence(schema.get("enum"))
    if not allowed:
        return
    for candidate in allowed:
        if _same_json_value(value, candidate):
            return
    listed = ", ".join(repr(item) for item in allowed)
    raise AISchemaError(f"{location} at {path} must be one of: {listed}; got {value!r}")


def _validate_bounds(
    value: object, schema: Mapping[str, object], *, location: str, path: str
) -> None:
    minimum = schema.get("minimum")
    maximum = schema.get("maximum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(minimum, (int, float)) and value < minimum:
            raise AISchemaError(f"{location} at {path} must be at least {minimum}, got {value!r}")
        if isinstance(maximum, (int, float)) and value > maximum:
            raise AISchemaError(f"{location} at {path} must be at most {maximum}, got {value!r}")
    if isinstance(value, str):
        _check_size(
            len(value), schema, "minLength", "at least", "character", location=location, path=path
        )
        _check_size(
            len(value), schema, "maxLength", "at most", "character", location=location, path=path
        )
    if isinstance(value, (list, tuple)):
        _check_size(
            len(value), schema, "minItems", "at least", "item", location=location, path=path
        )
        _check_size(len(value), schema, "maxItems", "at most", "item", location=location, path=path)


def _check_size(
    size: int,
    schema: Mapping[str, object],
    keyword: str,
    phrase: str,
    unit: str,
    *,
    location: str,
    path: str,
) -> None:
    limit = schema.get(keyword)
    if not isinstance(limit, int):
        return
    if (phrase == "at least" and size < limit) or (phrase == "at most" and size > limit):
        raise AISchemaError(
            f"{location} at {path} must have {phrase} {limit} {unit}(s), got {size}"
        )


def _validate_object(
    value: Mapping[object, object], schema: Mapping[str, object], *, location: str, path: str
) -> None:
    properties = schema.get("properties")
    declared = properties if isinstance(properties, Mapping) else {}
    for name in _sequence(schema.get("required")):
        if name not in value:
            raise AISchemaError(f"{location} at {path} is missing the required property {name!r}")
    for name, child in declared.items():
        if name in value and isinstance(child, Mapping):
            _validate_node(value[name], child, location=location, path=f"{path}.{name}")
    if schema.get("additionalProperties") is False:
        unexpected = sorted(str(name) for name in value if name not in declared)
        if unexpected:
            raise AISchemaError(
                f"{location} at {path} has unexpected propert(ies): {', '.join(unexpected)}"
            )


def _same_json_value(left: object, right: object) -> bool:
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    return bool(left == right)


def _sequence(value: object) -> Sequence[object]:
    """Return ``value`` as a sequence of items, or an empty one when it is not a JSON array."""
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return ()


def _described_types(declared: object) -> str:
    if declared is None:
        return "any value"
    if isinstance(declared, str):
        return declared
    return " or ".join(str(item) for item in _sequence(declared))


def _describe(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return type(value).__name__
