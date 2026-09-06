"""The stored shape of an event.

:class:`Event` is what the bus publishes and the store persists: the
envelope of 18 with ``data`` still a plain object. The typed view of the
same row is :data:`~athanore.events.payloads.EventEnvelope`, which is what
the API serialises and the SPA consumes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Event(BaseModel):
    """One event.

    ``id`` is the SSE cursor, assigned by the store; it is ``None`` before
    the insert and on ephemeral events (`task.stream`), which are never
    stored. ``run_id`` is absent on ``engine.*`` and ``task_id`` on every
    event that is not task-scoped.
    """

    id: int | None = None
    run_id: str | None = None
    task_id: int | None = None
    name: str
    data: dict[str, Any]
    created: datetime
