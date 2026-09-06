"""Coercion of node results and payloads into JSON-serializable values.

Everything the engine persists — a payload on a task row, a result, a
run output — passes through :func:`jsonable` first. The fallback is
``str`` rather than an exception: a workflow must not die because a body
returned something exotic, and 04 §Routing edge cases makes that
fallback the engine's cue to warn about a missing ``output_model``.
"""

from __future__ import annotations

import dataclasses
from typing import Any, cast

from pydantic import BaseModel

from athanore.graph.builder import Transition


def jsonable(value: Any) -> Any:
    """Coerce ``value`` into JSON-serializable structures.

    Pydantic models become ``model_dump(mode="json")``, ``Transition``
    becomes ``{"target", "payload"}``, other dataclasses become their
    ``asdict``, dicts and sequences are coerced element by element, and
    anything else falls back to ``str``.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Transition):
        return {"target": value.target, "payload": jsonable(value.payload)}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, dict):
        mapping = cast("dict[Any, Any]", value)
        return {key: jsonable(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast("list[Any] | tuple[Any, ...]", value)
        return [jsonable(item) for item in sequence]
    return str(value)
