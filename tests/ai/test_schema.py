"""The JSON Schema subset validates payloads and refuses to accept a schema it cannot honour."""

import pytest

from xyberos.ai import check_schema, describe_schema, validate_payload
from xyberos.errors import AIRequestError, AISchemaError

CITY_SCHEMA = {
    "type": "object",
    "properties": {
        "city": {"type": "string", "minLength": 2},
        "days": {"type": "integer", "minimum": 1, "maximum": 14},
        "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]},
        "tags": {"type": "array", "items": {"type": "string"}, "maxItems": 2},
    },
    "required": ["city"],
    "additionalProperties": False,
}


def test_a_conforming_payload_passes_through_unchanged() -> None:
    payload = {"city": "Oslo", "days": 3, "unit": "celsius", "tags": ["travel"]}

    assert validate_payload(payload, CITY_SCHEMA) is payload


def test_a_missing_required_property_is_reported_with_its_location() -> None:
    with pytest.raises(AISchemaError, match=r"at \$ is missing the required property 'city'"):
        validate_payload({"days": 3}, CITY_SCHEMA)


def test_a_wrong_type_is_reported_with_its_location() -> None:
    with pytest.raises(AISchemaError, match=r"at \$\.city must be string, got integer"):
        validate_payload({"city": 5}, CITY_SCHEMA)


def test_an_unexpected_property_is_rejected_when_additional_properties_is_false() -> None:
    with pytest.raises(AISchemaError, match=r"at \$ has unexpected propert\(ies\): sneaky"):
        validate_payload({"city": "Oslo", "sneaky": 1}, CITY_SCHEMA)


def test_bounds_and_sizes_are_enforced() -> None:
    with pytest.raises(AISchemaError, match=r"at \$\.city must have at least 2 character\(s\)"):
        validate_payload({"city": "O"}, CITY_SCHEMA)
    with pytest.raises(AISchemaError, match=r"at \$\.days must be at least 1"):
        validate_payload({"city": "Oslo", "days": 0}, CITY_SCHEMA)
    with pytest.raises(AISchemaError, match=r"at \$\.days must be at most 14"):
        validate_payload({"city": "Oslo", "days": 99}, CITY_SCHEMA)
    with pytest.raises(AISchemaError, match=r"at \$\.tags must have at most 2 item\(s\)"):
        validate_payload({"city": "Oslo", "tags": ["a", "b", "c"]}, CITY_SCHEMA)


def test_enum_membership_is_enforced() -> None:
    with pytest.raises(AISchemaError, match=r"at \$\.unit must be one of: 'celsius', 'fahrenheit'"):
        validate_payload({"city": "Oslo", "unit": "kelvin"}, CITY_SCHEMA)


def test_nested_array_items_are_validated_with_an_indexed_path() -> None:
    schema = {
        "type": "object",
        "properties": {"rows": {"type": "array", "items": {"type": "integer"}}},
    }

    validate_payload({"rows": [1, 2]}, schema)
    with pytest.raises(AISchemaError, match=r"at \$\.rows\[1\] must be integer, got string"):
        validate_payload({"rows": [1, "two"]}, schema)


def test_booleans_are_not_integers_and_integers_are_numbers() -> None:
    validate_payload(True, {"type": "boolean"})
    validate_payload(7, {"type": "number"})
    with pytest.raises(AISchemaError, match="must be integer, got boolean"):
        validate_payload(True, {"type": "integer"})
    with pytest.raises(AISchemaError, match="must be boolean, got integer"):
        validate_payload(1, {"type": "boolean"})


def test_an_enum_of_booleans_does_not_match_integers() -> None:
    schema = {"enum": [True, False]}

    validate_payload(True, schema)
    with pytest.raises(AISchemaError, match="must be one of"):
        validate_payload(1, schema)


def test_a_type_list_accepts_either_type() -> None:
    schema = {"type": ["string", "null"]}

    validate_payload("value", schema)
    validate_payload(None, schema)
    with pytest.raises(AISchemaError, match="must be string or null"):
        validate_payload(3, schema)


def test_an_unsupported_keyword_is_rejected_when_the_schema_is_declared() -> None:
    with pytest.raises(AIRequestError, match=r"uses unsupported keyword\(s\): oneOf"):
        check_schema({"type": "object", "oneOf": []}, location="response_schema")


def test_an_unsupported_type_is_rejected_when_the_schema_is_declared() -> None:
    with pytest.raises(AIRequestError, match=r"unsupported type 'date'"):
        check_schema({"type": "date"}, location="response_schema")


def test_a_schema_must_be_an_object_with_non_empty_property_names() -> None:
    with pytest.raises(AIRequestError, match="must be an object"):
        check_schema("not-a-schema", location="response_schema")
    with pytest.raises(AIRequestError, match=r"\$\.properties needs non-empty names"):
        check_schema({"type": "object", "properties": {"": {"type": "string"}}}, location="s")


def test_declared_schema_keywords_are_validated() -> None:
    with pytest.raises(AIRequestError, match=r"\.type must be a name or an array of names"):
        check_schema({"type": 5}, location="s")
    with pytest.raises(AIRequestError, match=r"\.enum must be a non-empty array"):
        check_schema({"enum": []}, location="s")
    with pytest.raises(AIRequestError, match=r"\.additionalProperties must be true or false"):
        check_schema({"additionalProperties": "no"}, location="s")
    with pytest.raises(AIRequestError, match=r"\.minLength must be a non-negative integer"):
        check_schema({"type": "string", "minLength": -1}, location="s")
    with pytest.raises(AIRequestError, match=r"\.minimum must be a number"):
        check_schema({"type": "number", "minimum": "low"}, location="s")
    with pytest.raises(AIRequestError, match=r"\.required must be an array of names"):
        check_schema({"type": "object", "required": "city"}, location="s")


def test_a_required_property_must_be_declared() -> None:
    with pytest.raises(AIRequestError, match=r"names undeclared propert\(ies\): city"):
        check_schema(
            {"type": "object", "properties": {"days": {"type": "integer"}}, "required": ["city"]},
            location="s",
        )


def test_annotation_keywords_are_accepted_and_ignored() -> None:
    schema = {
        "type": "string",
        "description": "a city",
        "title": "City",
        "default": "Oslo",
        "examples": ["Oslo"],
        "format": "text",
    }

    check_schema(schema, location="s")
    validate_payload("Bergen", schema)


def test_a_schema_without_a_type_still_checks_the_keywords_it_declares() -> None:
    validate_payload(3, {"minimum": 1})
    with pytest.raises(AISchemaError, match="must be at least 5"):
        validate_payload(3, {"minimum": 5})


def test_validate_payload_rechecks_the_schema_it_was_given() -> None:
    with pytest.raises(AIRequestError, match="unsupported keyword"):
        validate_payload({"a": 1}, {"type": "object", "notAKeyword": True})  # type: ignore[arg-type]


def test_describe_schema_summarises_the_declared_type() -> None:
    assert describe_schema({"type": "object"}) == "object"
    assert describe_schema({"type": ["string", "null"]}) == "string or null"
    assert describe_schema({"properties": {}}) == "object"
    assert describe_schema({}) == "any"
