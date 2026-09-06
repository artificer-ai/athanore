"""Tests for :mod:`athanore.requests.validators`.

Two properties carry the module. **A rejection is renderable**: an
answer that does not fit comes back as ``[{loc, msg, type}]`` with
``loc`` a *path*, because the SPA puts one entry next to one field and a
form three levels deep is the ordinary case (06 §Surfaces). **The subset
is closed**: every keyword 17 § ``T030`` names is enforced, accepted and
rejected below, and a keyword outside that list is ignored rather than
refused (D114) — so this file is also the list of what
``json_schema_validator`` does *not* promise.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field

from athanore.requests.errors import InvalidAnswer
from athanore.requests.validators import (
    json_schema_validator,
    pydantic_validator,
)


def rejects(schema: dict[str, Any], value: Any) -> list[dict[str, Any]]:
    """The errors ``schema`` reports for ``value``, which must not fit."""
    with pytest.raises(InvalidAnswer) as caught:
        json_schema_validator(schema)(value)
    assert caught.value.errors, "a rejection must say what was wrong"
    return caught.value.errors


def accepts(schema: dict[str, Any], value: Any) -> None:
    """``value`` fits ``schema``, and comes back unchanged and identical."""
    assert json_schema_validator(schema)(value) is value


def locs(errors: list[dict[str, Any]]) -> list[Any]:
    return [error["loc"] for error in errors]


def types(errors: list[dict[str, Any]]) -> list[str]:
    return [error["type"] for error in errors]


# --------------------------------------------------------------------------
# pydantic_validator
# --------------------------------------------------------------------------


class Inner(BaseModel):
    scores: list[int]


class Outer(BaseModel):
    inner: Inner
    label: str = Field(min_length=1)


def test_pydantic_validator_returns_the_model_instance() -> None:
    """The instance, not a dump: the body was promised an ``Outer``."""
    validate = pydantic_validator(Outer)

    result = validate({"inner": {"scores": [1, 2]}, "label": "ok"})

    assert isinstance(result, Outer)
    assert result.inner.scores == [1, 2]


def test_pydantic_validator_keeps_the_nested_loc_path() -> None:
    """``("inner", "scores", 0)`` — the field the form must highlight."""
    validate = pydantic_validator(Outer)

    with pytest.raises(InvalidAnswer) as caught:
        validate({"inner": {"scores": ["nope"]}, "label": "ok"})

    assert locs(caught.value.errors) == [("inner", "scores", 0)]
    assert types(caught.value.errors) == ["int_parsing"]


def test_pydantic_validator_reports_every_failure() -> None:
    """A form shows all of its errors at once, so all of them are kept."""
    validate = pydantic_validator(Outer)

    with pytest.raises(InvalidAnswer) as caught:
        validate({"inner": {}, "label": ""})

    assert sorted(locs(caught.value.errors)) == [
        ("inner", "scores"),
        ("label",),
    ]


def test_pydantic_validator_narrows_to_three_keys() -> None:
    """``input``/``url``/``ctx`` are pydantic's, not the form's."""
    validate = pydantic_validator(Inner)

    with pytest.raises(InvalidAnswer) as caught:
        validate({"scores": "no"})

    assert [set(error) for error in caught.value.errors] == [{"loc", "msg", "type"}]


def test_pydantic_validator_rejects_a_non_object() -> None:
    """A ``form`` answer that is not an object fails like any other."""
    validate = pydantic_validator(Inner)

    with pytest.raises(InvalidAnswer) as caught:
        validate("a string")

    assert caught.value.errors
    assert "Inner" in str(caught.value)


# --------------------------------------------------------------------------
# json_schema_validator: type, including unions
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("string", "text"),
        ("number", 1),
        ("number", 1.5),
        ("integer", 3),
        ("boolean", True),
        ("object", {"a": 1}),
        ("array", [1]),
        ("null", None),
    ],
)
def test_type_accepts(name: str, value: Any) -> None:
    accepts({"type": name}, value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("string", 1),
        ("number", "1"),
        ("integer", 1.5),
        ("boolean", "true"),
        ("object", [1]),
        ("array", {"a": 1}),
        ("null", 0),
    ],
)
def test_type_rejects(name: str, value: Any) -> None:
    errors = rejects({"type": name}, value)

    assert types(errors) == ["type"]
    assert locs(errors) == [()]
    assert name in errors[0]["msg"]


def test_a_boolean_is_not_a_number() -> None:
    """``True`` is an ``int`` in Python and is not one in JSON."""
    rejects({"type": "integer"}, True)
    rejects({"type": "number"}, False)


def test_type_union_accepts_either_member() -> None:
    schema = {"type": ["string", "null"]}

    accepts(schema, "text")
    accepts(schema, None)


def test_type_union_rejects_a_third_type() -> None:
    errors = rejects({"type": ["string", "null"]}, 7)

    assert types(errors) == ["type"]
    assert errors[0]["msg"] == "expected string or null"


def test_a_wrong_type_is_reported_once() -> None:
    """No cascade: the other keywords are about a value that is not there."""
    errors = rejects({"type": "string", "minLength": 5, "pattern": "^a"}, 12)

    assert types(errors) == ["type"]


# --------------------------------------------------------------------------
# json_schema_validator: objects
# --------------------------------------------------------------------------


PERSON: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer"},
    },
    "required": ["name"],
}


def test_required_accepts_when_present() -> None:
    accepts(PERSON, {"name": "ada"})


def test_required_rejects_when_absent() -> None:
    errors = rejects(PERSON, {"age": 36})

    assert locs(errors) == [("name",)]
    assert types(errors) == ["missing"]


def test_properties_validate_their_own_values() -> None:
    errors = rejects(PERSON, {"name": "ada", "age": "old"})

    assert locs(errors) == [("age",)]
    assert types(errors) == ["type"]


def test_properties_ignore_a_key_the_value_does_not_carry() -> None:
    """An absent optional property is not a failure."""
    accepts(PERSON, {"name": "ada"})


def test_additional_properties_false_rejects_an_unexpected_key() -> None:
    schema = {**PERSON, "additionalProperties": False}

    errors = rejects(schema, {"name": "ada", "nickname": "the countess"})

    assert locs(errors) == [("nickname",)]
    assert types(errors) == ["extra_forbidden"]


def test_additional_properties_false_accepts_the_declared_keys() -> None:
    accepts({**PERSON, "additionalProperties": False}, {"name": "ada", "age": 36})


def test_additional_properties_true_permits_anything() -> None:
    """Only ``false`` constrains; ``true`` is the default said out loud."""
    accepts({**PERSON, "additionalProperties": True}, {"name": "ada", "x": 1})


def test_object_keywords_do_not_apply_to_a_non_object() -> None:
    """``required`` says nothing about a list, as in JSON Schema proper."""
    accepts({"required": ["name"]}, [1, 2])


# --------------------------------------------------------------------------
# json_schema_validator: enum and const
# --------------------------------------------------------------------------


def test_enum_accepts_a_listed_value() -> None:
    accepts({"enum": ["red", "green"]}, "green")


def test_enum_rejects_an_unlisted_value() -> None:
    errors = rejects({"enum": ["red", "green"]}, "blue")

    assert types(errors) == ["enum"]
    assert "red" in errors[0]["msg"]


def test_enum_does_not_confuse_true_with_one() -> None:
    """JSON equality, not Python's, where ``True == 1``."""
    accepts({"enum": [1]}, 1)
    rejects({"enum": [1]}, True)


def test_const_accepts_the_one_value() -> None:
    accepts({"const": "yes"}, "yes")


def test_const_rejects_anything_else() -> None:
    errors = rejects({"const": "yes"}, "no")

    assert types(errors) == ["const"]


# --------------------------------------------------------------------------
# json_schema_validator: arrays
# --------------------------------------------------------------------------


TAGS: dict[str, Any] = {
    "type": "array",
    "items": {"type": "string"},
    "minItems": 2,
}


def test_items_accepts_a_matching_list() -> None:
    accepts(TAGS, ["a", "b"])


def test_items_rejects_the_offending_element_by_index() -> None:
    errors = rejects(TAGS, ["a", 2, "c"])

    assert locs(errors) == [(1,)]
    assert types(errors) == ["type"]


def test_min_items_accepts_the_boundary() -> None:
    accepts(TAGS, ["a", "b"])


def test_min_items_rejects_a_short_list() -> None:
    errors = rejects(TAGS, ["a"])

    assert types(errors) == ["too_short"]
    assert locs(errors) == [()]


def test_array_keywords_do_not_apply_to_a_string() -> None:
    """``minItems`` counts elements, and a string has none to count."""
    accepts({"minItems": 5}, "ab")


# --------------------------------------------------------------------------
# json_schema_validator: numbers and strings
# --------------------------------------------------------------------------


def test_minimum_and_maximum_are_inclusive() -> None:
    accepts({"type": "number", "minimum": 1, "maximum": 10}, 1)
    accepts({"type": "number", "minimum": 1, "maximum": 10}, 10)


def test_minimum_rejects_below() -> None:
    errors = rejects({"type": "number", "minimum": 1}, 0.5)

    assert types(errors) == ["greater_than_equal"]


def test_maximum_rejects_above() -> None:
    errors = rejects({"type": "integer", "maximum": 10}, 11)

    assert types(errors) == ["less_than_equal"]


def test_bounds_do_not_apply_to_a_string() -> None:
    accepts({"minimum": 5}, "a")


def test_min_length_and_max_length() -> None:
    accepts({"type": "string", "minLength": 1, "maxLength": 3}, "ab")
    assert types(rejects({"minLength": 2}, "a")) == ["too_short"]
    assert types(rejects({"maxLength": 2}, "abc")) == ["too_long"]


def test_pattern_accepts_and_rejects() -> None:
    accepts({"type": "string", "pattern": "^v[0-9]+$"}, "v12")

    errors = rejects({"type": "string", "pattern": "^v[0-9]+$"}, "12")

    assert types(errors) == ["string_pattern_mismatch"]


def test_pattern_is_unanchored_like_json_schema() -> None:
    """``pattern`` is a search, not a full match (JSON Schema §pattern)."""
    accepts({"pattern": "b"}, "abc")


def test_an_unparseable_pattern_constrains_nothing() -> None:
    """The schema author's defect, not the answer's."""
    accepts({"pattern": "["}, "anything")


# --------------------------------------------------------------------------
# json_schema_validator: paths, accumulation, and the closed subset
# --------------------------------------------------------------------------


NESTED: dict[str, Any] = {
    "type": "object",
    "properties": {
        "outer": {
            "type": "object",
            "properties": {
                "inner": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["inner"],
        },
    },
    "required": ["outer"],
}


def test_nested_loc_path_survives() -> None:
    """``("outer", "inner", 0)``: three levels, one renderable field."""
    errors = rejects(NESTED, {"outer": {"inner": [7]}})

    assert locs(errors) == [("outer", "inner", 0)]


def test_a_missing_nested_key_is_located_under_its_parent() -> None:
    errors = rejects(NESTED, {"outer": {}})

    assert locs(errors) == [("outer", "inner")]
    assert types(errors) == ["missing"]


def test_every_failure_is_reported() -> None:
    """A form shows all of its errors at once."""
    schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 2},
            "age": {"type": "integer", "minimum": 0},
        },
        "required": ["email"],
        "additionalProperties": False,
    }

    errors = rejects(schema, {"name": "a", "age": -1, "extra": True})

    assert sorted(types(errors)) == [
        "extra_forbidden",
        "greater_than_equal",
        "missing",
        "too_short",
    ]


def test_a_value_that_fits_comes_back_unchanged() -> None:
    """The validator normalises nothing: T031 stores what it returns."""
    value = {"name": "ada", "age": 36}

    assert json_schema_validator(PERSON)(value) is value


def test_an_empty_schema_accepts_anything() -> None:
    accepts({}, {"whatever": [1, 2, 3]})


def test_an_unsupported_keyword_is_ignored_not_refused() -> None:
    """D114: an agent's ``uniqueItems`` must not make a request
    unanswerable. The cost is that it does not constrain."""
    accepts({"type": "array", "uniqueItems": True}, [1, 1])
    accepts({"type": "string", "format": "email"}, "not-an-email")
    accepts({"allOf": [{"type": "string"}]}, 7)


def test_an_unknown_type_name_constrains_nothing() -> None:
    accepts({"type": "any"}, 7)
    accepts({"type": ["any", "whatever"]}, 7)


def test_a_malformed_type_value_constrains_nothing() -> None:
    """A `type` that is not a name or a list of them is ignored, not a crash.

    These schemas arrive over a wire an agent writes, so `{"type": 1}`
    must behave like every other construct this subset cannot honour."""
    accepts({"type": True}, "anything")
    accepts({"type": 123}, "anything")
    accepts({"type": {"name": "string"}}, 7)
    accepts({"type": ["string", 7, ["nested"]]}, "a string")
    assert types(rejects({"type": ["string", 7, ["nested"]]}, 42)) == ["type"]
    accepts({"type": []}, 7)
    accepts(
        {"type": "object", "properties": {"a": {"type": None}}},
        {"a": 7},
    )


def test_a_malformed_required_member_constrains_nothing() -> None:
    """A `required` member that is not a property name is ignored.

    An unhashable member would raise out of the membership test, and a
    hashable non-string one would demand a key no JSON object can carry,
    leaving a request nobody can answer. The string members beside it
    are still enforced."""
    accepts({"type": "object", "required": [["b"]]}, {"a": 1})
    accepts({"type": "object", "required": [{"name": "a"}]}, {"a": 1})
    accepts({"type": "object", "required": [1, None, True]}, {"a": 1})
    assert locs(rejects({"type": "object", "required": ["a", ["b"], 1]}, {"c": 1})) == [
        ("a",)
    ]


def test_a_non_object_subschema_is_ignored() -> None:
    """``True``/``False`` are legal schemas this subset does not implement."""
    accepts({"type": "object", "properties": {"a": True}}, {"a": 1})
    accepts({"type": "array", "items": False}, [1])


def test_invalid_answer_without_details_still_has_a_list() -> None:
    """``errors`` is always a list — T042 puts it on the wire either way."""
    assert InvalidAnswer("text answer must be a non-empty string").errors == []
