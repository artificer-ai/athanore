"""The event envelope, re-exported for the API (18 §Typing, D81).

18 fixes one pydantic model per event name and a discriminated
:data:`~athanore.events.payloads.EventEnvelope` over them, and puts those
models in :mod:`athanore.events.payloads` — below the API, where the bus
and the store can reach them too. This module is the name 18 §Typing gives
that union on the API side, and it **re-exports** rather than restates:
two declarations of the same wire shape are two things to keep in step,
and the union is what ``GET /api/runs/{id}/events`` and every SSE
``data:`` line serialise.

The payloads type the fields 18 gives a domain enum (``RunStatus``,
``TaskStatus``, ``RequestMode``, …) as ``str``, because
:mod:`athanore.events` is an independent sibling of
:mod:`athanore.store` and may not import its enums (02 §Layering, D81).
They are left as ``str`` here too: narrowing them would mean restating
every payload that carries one, which is exactly what 18 §Typing says not
to do.
"""

from __future__ import annotations

from athanore.events.payloads import ENVELOPES, PAYLOADS, EventEnvelope, EventFrame

__all__ = ["ENVELOPES", "PAYLOADS", "EventEnvelope", "EventFrame"]
