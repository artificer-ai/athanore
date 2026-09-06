"""The two validators a `form` request can register (06 §Service).

A form answer is validated *where it lands* — in
``RequestService.answer`` (T031), against a callable the waiter
registered when it opened the request — so an answer is refused at the
moment it is given, to the face that gave it, rather than in a node body
several seconds later. This module is the two callables anyone
registers:

- :func:`pydantic_validator`, for a request opened from a pydantic model
  (``human_input(output_model=M)``): the model *is* the schema, and the
  validated instance is worth keeping, so the validator returns it;
- :func:`json_schema_validator`, for a request opened from a JSON schema
  that arrived over a wire — an ACP elicitation's ``requestedSchema``,
  an HTTP ask's ``schema`` — where there is no model to validate
  against, only a document. It returns the value unchanged.

Both raise :exc:`~athanore.requests.errors.InvalidAnswer` carrying
``[{loc, msg, type}]`` entries, in pydantic's shape, whichever produced
them: the SPA renders one entry next to one field, so ``loc`` is a
**path** — ``("outer", "inner", 0)`` for the first element of
``outer.inner`` — and a flat message would be useless to the form that
has to display it.

## The JSON-schema subset

:func:`json_schema_validator` is deliberately not a JSON Schema
implementation. It supports exactly the keywords 17 § ``T030`` names —
``type`` (a single name or a union of names), ``required``,
``properties``, ``additionalProperties: false``, ``enum``, ``const``,
``items``, ``minItems``, ``minimum``/``maximum``,
``minLength``/``maxLength``, ``pattern`` — recursively, through
``properties`` and ``items``.

Anything else in the schema is **ignored, not rejected** (D114): these
schemas are written by an agent or by a plugin author, and a validator
that refused ``$defs`` or ``uniqueItems`` would turn a keyword it merely
does not enforce into a request nobody can answer. The cost is that an
unsupported constraint silently does not constrain, which is why the
supported list is closed and enumerated here rather than grown ad hoc.

The same rule covers a keyword this subset *does* support whose value is
the wrong shape — ``"type": 1``, a ``required`` member that is not a
property name — down to the members of a list, not just the list. Such a
construct constrains nothing. It is never a crash and never a demand no
answer can meet: the schema came off a wire an agent writes, and either
outcome would leave a request nobody can answer.

As in JSON Schema proper, a keyword only constrains the type it applies
to: ``minimum`` says nothing about a string, ``properties`` says nothing
about a list. A value of the wrong type is reported once, by ``type``,
instead of once per keyword that could not apply.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from athanore.requests.errors import InvalidAnswer

#: One machine-readable entry of :attr:`InvalidAnswer.errors`: ``loc``
#: (the path to the offending value, a tuple), ``msg`` (for a human) and
#: ``type`` (a stable code for the SPA).
ErrorDict = dict[str, Any]

#: What a registered validator is: a callable that takes the answer as
#: it arrived and returns the value to store, or raises
#: :exc:`InvalidAnswer`.
Validator = Callable[[Any], Any]

#: The Python types each JSON type name accepts. ``bool`` is excluded
#: from ``integer`` and ``number`` explicitly below: it is a subclass of
#: ``int`` in Python and is not a number in JSON.
_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "object": dict,
    "array": list,
    "null": type(None),
}


def pydantic_validator(model: type[BaseModel]) -> Callable[[Any], BaseModel]:
    """A validator that validates against ``model`` and returns the instance.

    The instance, not a dump: ``human_input(output_model=M)`` promises
    the body an ``M`` (06 §The model), and the round trip through
    ``model_dump`` would lose every non-JSON type the model declares.
    T031 is what decides how the returned value is stored.

    A :exc:`~pydantic.ValidationError` becomes an
    :exc:`~athanore.requests.errors.InvalidAnswer` whose ``errors`` are
    pydantic's own, narrowed to ``loc``/``msg``/``type``: the other keys
    pydantic reports (``input``, ``url``, ``ctx``) either echo the
    answer back or point at pydantic's documentation, neither of which
    the form rendering the failure has any use for.
    """

    def validate(value: Any) -> BaseModel:
        try:
            return model.model_validate(value)
        except ValidationError as exc:
            raise InvalidAnswer(
                f"answer does not fit {model.__name__}",
                _pydantic_errors(exc),
            ) from exc

    return validate


def json_schema_validator(schema: dict[str, Any]) -> Validator:
    """A validator for ``schema``, returning the answer unchanged.

    The supported keyword subset is the module docstring's; an
    unsupported keyword is ignored. Every failure in the value is
    reported, not just the first, because a form shows all of its errors
    at once.
    """

    def validate(value: Any) -> Any:
        errors = _check(value, schema, ())
        if errors:
            raise InvalidAnswer("answer does not match the requested schema", errors)
        return value

    return validate


# --------------------------------------------------------------------------
# The subset, one function per applicable type
# --------------------------------------------------------------------------


def _check(value: Any, schema: Any, loc: tuple[Any, ...]) -> list[ErrorDict]:
    """Every error in ``value`` against ``schema``, located at ``loc``.

    A schema that is not an object constrains nothing — ``True``,
    ``False`` and a stray string are all legal JSON Schema documents
    this subset does not implement — so it is ignored like any other
    unsupported keyword.
    """
    if not isinstance(schema, dict):
        return []
    errors: list[ErrorDict] = []
    type_error = _check_type(value, schema, loc)
    if type_error is not None:
        # The type is wrong, so every other keyword is about a value
        # that is not there. One error, not a cascade.
        return [type_error]
    errors += _check_enum(value, schema, loc)
    if isinstance(value, dict):
        errors += _check_object(value, schema, loc)
    if isinstance(value, list):
        errors += _check_array(value, schema, loc)
    if isinstance(value, str):
        errors += _check_string(value, schema, loc)
    if isinstance(value, int | float) and not isinstance(value, bool):
        errors += _check_number(value, schema, loc)
    return errors


def _check_type(
    value: Any, schema: dict[str, Any], loc: tuple[Any, ...]
) -> ErrorDict | None:
    """``type``: one name, or a union of them. ``None`` when it fits."""
    declared = schema.get("type")
    if isinstance(declared, str):
        names: list[Any] = [declared]
    elif isinstance(declared, Sequence) and not isinstance(declared, bytes):
        names = list(declared)
    else:
        # `type` is neither a name nor a list of them (`true`, `1`, an
        # object): a malformed construct, which constrains nothing like
        # any other this subset cannot honour. It is not a crash — these
        # schemas come off a wire an agent writes.
        return None
    # A name this subset does not know (a `$ref`ed type, a JSON Schema
    # draft's `any`), or one that is not a name at all, constrains
    # nothing rather than rejecting everything.
    known = [name for name in names if isinstance(name, str) and name in _JSON_TYPES]
    if not known:
        return None
    if any(_is_type(value, name) for name in known):
        return None
    return _error(loc, f"expected {' or '.join(known)}", "type")


def _is_type(value: Any, name: str) -> bool:
    """Whether ``value`` is JSON type ``name``."""
    if name in ("integer", "number") and isinstance(value, bool):
        return False  # `True` is an `int` in Python but not a number in JSON
    return isinstance(value, _JSON_TYPES[name])


def _check_enum(
    value: Any, schema: dict[str, Any], loc: tuple[Any, ...]
) -> list[ErrorDict]:
    """``enum`` and ``const``, the two ways a schema names its values."""
    errors: list[ErrorDict] = []
    enum = schema.get("enum")
    if isinstance(enum, Sequence) and not isinstance(enum, str | bytes):
        if not any(_json_equal(value, allowed) for allowed in enum):
            errors.append(_error(loc, f"must be one of {list(enum)}", "enum"))
    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(_error(loc, f"must be {schema['const']!r}", "const"))
    return errors


def _check_object(
    value: dict[Any, Any], schema: dict[str, Any], loc: tuple[Any, ...]
) -> list[ErrorDict]:
    """``required``, ``properties`` and ``additionalProperties: false``."""
    errors: list[ErrorDict] = []
    properties = schema.get("properties")
    properties = properties if isinstance(properties, dict) else {}
    required = schema.get("required")
    if isinstance(required, Sequence) and not isinstance(required, str | bytes):
        # A member that is not a property name (a nested list, an object,
        # a number) constrains nothing, like every other malformed
        # construct: enforcing it would either raise on an unhashable key
        # or demand one no JSON object can carry, leaving a request
        # nobody can answer.
        for key in (name for name in required if isinstance(name, str)):
            if key not in value:
                errors.append(_error((*loc, key), "Field required", "missing"))
    for key, subschema in properties.items():
        if key in value:
            errors += _check(value[key], subschema, (*loc, key))
    if schema.get("additionalProperties") is False:
        for key in value:
            if key not in properties:
                errors.append(
                    _error(
                        (*loc, key),
                        "Extra inputs are not permitted",
                        "extra_forbidden",
                    )
                )
    return errors


def _check_array(
    value: list[Any], schema: dict[str, Any], loc: tuple[Any, ...]
) -> list[ErrorDict]:
    """``items`` (one schema for every element) and ``minItems``."""
    errors: list[ErrorDict] = []
    minimum = schema.get("minItems")
    if isinstance(minimum, int) and not isinstance(minimum, bool):
        if len(value) < minimum:
            errors.append(
                _error(loc, f"must have at least {minimum} items", "too_short")
            )
    if "items" in schema:
        for index, item in enumerate(value):
            errors += _check(item, schema["items"], (*loc, index))
    return errors


def _check_string(
    value: str, schema: dict[str, Any], loc: tuple[Any, ...]
) -> list[ErrorDict]:
    """``minLength``, ``maxLength`` and ``pattern``."""
    errors: list[ErrorDict] = []
    minimum = schema.get("minLength")
    if isinstance(minimum, int) and not isinstance(minimum, bool):
        if len(value) < minimum:
            errors.append(
                _error(
                    loc,
                    f"must have at least {minimum} characters",
                    "too_short",
                )
            )
    maximum = schema.get("maxLength")
    if isinstance(maximum, int) and not isinstance(maximum, bool):
        if len(value) > maximum:
            errors.append(
                _error(loc, f"must have at most {maximum} characters", "too_long")
            )
    pattern = schema.get("pattern")
    if isinstance(pattern, str):
        try:
            matches = re.search(pattern, value) is not None
        except re.error:
            # An unparseable pattern is the schema author's defect, not
            # the answer's: it cannot be honoured, so it is ignored like
            # any other keyword this subset does not implement.
            matches = True
        if not matches:
            errors.append(
                _error(
                    loc,
                    f"must match {pattern}",
                    "string_pattern_mismatch",
                )
            )
    return errors


def _check_number(
    value: float, schema: dict[str, Any], loc: tuple[Any, ...]
) -> list[ErrorDict]:
    """``minimum`` and ``maximum``, both inclusive."""
    errors: list[ErrorDict] = []
    minimum = schema.get("minimum")
    if isinstance(minimum, int | float) and not isinstance(minimum, bool):
        if value < minimum:
            errors.append(
                _error(
                    loc,
                    f"must be greater than or equal to {minimum}",
                    "greater_than_equal",
                )
            )
    maximum = schema.get("maximum")
    if isinstance(maximum, int | float) and not isinstance(maximum, bool):
        if value > maximum:
            errors.append(
                _error(
                    loc,
                    f"must be less than or equal to {maximum}",
                    "less_than_equal",
                )
            )
    return errors


# --------------------------------------------------------------------------
# Shared
# --------------------------------------------------------------------------


def _error(loc: tuple[Any, ...], msg: str, type_: str) -> ErrorDict:
    """One ``{loc, msg, type}`` entry, in pydantic's shape."""
    return {"loc": loc, "msg": msg, "type": type_}


def _json_equal(value: Any, other: Any) -> bool:
    """JSON equality, which is not Python's for booleans.

    ``True == 1`` in Python, so a plain ``==`` would accept ``true`` for
    an ``enum: [1]`` — the same confusion :func:`_is_type` keeps out of
    ``integer``.
    """
    if isinstance(value, bool) != isinstance(other, bool):
        return False
    return bool(value == other)


def _pydantic_errors(exc: ValidationError) -> list[ErrorDict]:
    """Pydantic's errors, narrowed to the three keys the SPA renders."""
    return [
        {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]


__all__ = [
    "ErrorDict",
    "Validator",
    "json_schema_validator",
    "pydantic_validator",
]
