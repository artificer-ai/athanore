"""``GET /api/events``: the one live stream (08 §Events).

Every client — the SPA, a CLI that follows a run, a plugin panel — reads
one stream per tab and filters it server-side. The endpoint's whole
difficulty is the seam between the two halves of that stream: a client
reconnects with a cursor, gets the history it missed from the store, and
then gets events as they happen from the bus. Across that seam nothing
may be lost and nothing may arrive twice.

Both hazards are handled in one place, and neither by luck:

- **Nothing is lost**, because the subscription is taken *before* the
  replay query runs. The store commits and then publishes (07 §Unit of
  work and outbox), so an event committed while the replay is in flight
  is already queued on a subscription that existed first. Subscribing
  afterwards would drop every event in between — the missed-wake bug in
  its second form.
- **Nothing arrives twice**, because that same ordering means the
  overlap is real: an event can be both in the replay result and in the
  queue. The live loop therefore drops anything whose id is at or below
  the last id replayed. Ids ascend in emission order (``EventRepo``), so
  a single high-water mark is the whole of the de-duplication.

Two frames are not stored events, and both say the same thing to the
client — *your history has a hole in it, refetch*:

- the replay found more than ``sse_replay_cap`` events, so the client is
  further behind than one page. Sending a truncated history it would
  believe was complete is worse than sending none, so none is sent;
- the subscription overflowed. The bus never awaits a subscriber (D29),
  so a reader that falls behind loses events rather than stalling every
  writer in the process, and ``Subscription.overflowed`` is the sticky
  flag that says so.

``task.stream`` is the one event that is published but never stored (03).
It is sent **without an ``id:`` line**, so a browser's
``Last-Event-ID`` — which it would otherwise overwrite — always names a
stored event the store can replay from.

The frames are serialised through the same
:data:`~athanore.events.payloads.EventEnvelope` adapter that
``GET /api/runs/{id}/events`` returns, so a client that caught up over
REST and then subscribed here sees one shape, not two (18 §Typing, D53).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import TypeAdapter
from sse_starlette.sse import EventSourceResponse

from athanore.api.deps import operator_auth
from athanore.api.errors import ApiError, ErrorCode
from athanore.api.schemas import EventEnvelope
from athanore.engine import Engine
from athanore.events.bus import EventBus, Subscription
from athanore.events.model import Event
from athanore.settings import AthanoreSettings
from athanore.store.rows import EventRow
from athanore.store.uow import Store

__all__ = ["OVERFLOWED", "REPLAY_CAPPED", "RESYNC", "ResyncReason", "router"]

router = APIRouter(
    prefix="/api",
    tags=["events"],
    dependencies=[Depends(operator_auth)],
)

#: The name of the control frame that tells a client to refetch. It is
#: not part of the event vocabulary — nothing publishes it and nothing
#: stores it — so it carries no ``id:`` and lives here rather than in
#: ``events/names.py``.
RESYNC: Final = "resync"

#: Why a :data:`RESYNC` was sent. The client's action is the same either
#: way (10 §Realtime clears its cursor and invalidates its queries); the
#: reason is what makes a stream that resyncs often diagnosable.
ResyncReason = str

#: The client is further behind than ``sse_replay_cap`` events.
REPLAY_CAPPED: Final[ResyncReason] = "replay_capped"

#: The bus dropped events for this subscription because it fell behind.
OVERFLOWED: Final[ResyncReason] = "overflowed"

#: The characters ``EventRepo``'s glob refuses (D87): a character class
#: has no ``LIKE`` equivalent, so a replay could not be made to agree
#: with the live filter and the pattern is refused at the door instead.
_UNSUPPORTED_GLOB: Final = frozenset("[]")

#: One event as the typed envelope of 18. Built once: a ``TypeAdapter``
#: compiles its validator and its serialiser on construction.
_ENVELOPE: Final[TypeAdapter[EventEnvelope]] = TypeAdapter(EventEnvelope)


def _bus(request: Request) -> EventBus | None:
    """The bus this application's events are published to, if it has one.

    The engine and the store are handed the *same* bus by whichever host
    built them, so either is the right place to ask; the engine is asked
    first only because its attribute is typed as the bus rather than as
    the narrower publisher protocol the store keeps.

    ``None`` is a real answer: ``create_app()`` with neither collaborator
    is what the OpenAPI dump builds (04 §Shutdown), and nothing in that
    application can ever publish. Such a stream replays what a store
    holds, if there is one, and then stays open — which is the truth,
    rather than a stream that claims to be live.
    """

    engine: Engine | None = request.app.state.engine
    if engine is not None:
        return engine.bus
    store: Store | None = request.app.state.store
    if store is not None and isinstance(store.bus, EventBus):
        return store.bus
    return None


def _invalid(location: Sequence[str | int], message: str) -> ApiError:
    """The 422 of 08 §Conventions for one bad query parameter."""

    return ApiError(
        422,
        ErrorCode.validation,
        "validation failed",
        errors=[{"loc": list(location), "msg": message, "type": "value_error"}],
    )


def _patterns(names: str | None) -> tuple[str, ...] | None:
    """``names`` as the globs to filter by, or ``None`` for every event.

    Comma-separated, whitespace around each one ignored, and empty
    entries dropped: ``names=`` and ``names=run.*,`` both mean what they
    look like. A ``names`` that selects nothing at all is no filter
    rather than a stream that could never carry a frame — the same
    reading ``EventRepo.list_after`` gives an empty ``patterns``.
    """

    if names is None:
        return None
    patterns = tuple(part.strip() for part in names.split(",") if part.strip())
    if not patterns:
        return None
    for pattern in patterns:
        if _UNSUPPORTED_GLOB & set(pattern):
            raise _invalid(
                ("query", "names"),
                f"event pattern {pattern!r} uses a character class, which the "
                "event-name glob does not support; use * and ? only",
            )
    return patterns


def _cursor(after: int | None, last_event_id: str | None) -> int:
    """Where to replay from: ``after``, else ``Last-Event-ID``, else 0.

    The query parameter wins when both are present. A browser sets the
    header by itself on reconnect and only ever echoes an id this
    endpoint sent, so a header that is not a non-negative integer came
    from a client that made it up, and saying so is more use than
    silently replaying that client's whole history.
    """

    if after is not None:
        return after
    if last_event_id is None:
        return 0
    try:
        cursor = int(last_event_id)
    except ValueError:
        cursor = -1
    if cursor < 0:
        raise _invalid(
            ("header", "last-event-id"),
            f"Last-Event-ID must be a non-negative event id; got {last_event_id!r}",
        )
    return cursor


def _data(
    *,
    event_id: int | None,
    run_id: str | None,
    task_id: int | None,
    name: str,
    data: dict[str, Any],
    created: Any,
) -> str:
    """One event as the JSON of a ``data:`` line.

    Validated through the published union rather than hand-assembled: the
    shape of ``data`` is fixed per event name (18 §Payloads), and this is
    the same adapter ``GET /api/runs/{id}/events`` returns through, so
    history and live cannot drift into two shapes. An event the
    vocabulary cannot type is a defect at the publisher and surfaces as
    one.
    """

    envelope = _ENVELOPE.validate_python(
        {
            "id": event_id,
            "run_id": run_id,
            "task_id": task_id,
            "name": name,
            "data": data,
            "created": created,
        }
    )
    return _ENVELOPE.dump_json(envelope).decode("utf-8")


def _stored_frame(row: EventRow) -> dict[str, str]:
    """A replayed row: the cursor, the name, the envelope."""

    return {
        "id": str(row.id),
        "event": row.name,
        "data": _data(
            event_id=row.id,
            run_id=row.run_id,
            task_id=row.task_id,
            name=row.name,
            data=row.data,
            created=row.created,
        ),
    }


def _live_frame(event: Event) -> dict[str, str]:
    """A published event.

    ``id`` is present exactly when the event was stored. An ephemeral one
    (``task.stream``) has none, and the frame carries no ``id:`` line, so
    a reconnecting client's ``Last-Event-ID`` still names a row the store
    can replay from (08 §Events).
    """

    frame = {
        "event": event.name,
        "data": _data(
            event_id=event.id,
            run_id=event.run_id,
            task_id=event.task_id,
            name=event.name,
            data=event.data,
            created=event.created,
        ),
    }
    if event.id is not None:
        frame["id"] = str(event.id)
    return frame


def _resync_frame(reason: ResyncReason) -> dict[str, str]:
    """The control frame: no ``id:``, and a body a client can act on.

    A frame with no ``data:`` line is not dispatched by a browser's
    ``EventSource`` at all, so the reason is not decoration — it is what
    makes the frame arrive.
    """

    return {"event": RESYNC, "data": json.dumps({"reason": reason})}


async def _page(
    store: Store,
    after: int,
    cap: int,
    run_id: str | None,
    patterns: tuple[str, ...] | None,
) -> tuple[list[EventRow], bool]:
    """One page of history after ``after``, and whether it overran ``cap``.

    ``cap + 1`` rows are read so that "there is more than a page" is
    answered by the same query that fetches the page, without a count
    over a table whose whole point is that it grows.
    """

    async with store.reader() as reader:
        rows = await reader.events.list_after(after, cap + 1, run_id, patterns)
    return (rows, len(rows) > cap)


async def _replay(
    store: Store,
    after: int,
    cap: int,
    run_id: str | None,
    patterns: tuple[str, ...] | None,
) -> tuple[list[EventRow], bool]:
    """:func:`_page`, run where a disconnect cannot interrupt it.

    This is the one place in the stream that holds a pooled connection,
    and a client abandoning the request *during* the replay is ordinary —
    a browser closing a tab does it. Cancellation would land inside the
    read and then inside the connection's own ``close``, leaving
    SQLAlchemy to terminate a connection that was never checked back in
    (and to say so, from the garbage collector, long afterwards).

    The read therefore runs in its own task, shielded: the caller is
    cancelled at once, as it should be, and the query and its cleanup
    finish on their own. The task cannot outlive its work — it is one
    ``SELECT`` with a ``LIMIT`` — and the shield holds the reference that
    keeps it alive to the end.
    """

    return await asyncio.shield(
        asyncio.create_task(_page(store, after, cap, run_id, patterns))
    )


async def _live(
    subscription: Subscription,
    last_id: int,
    run_id: str | None,
) -> AsyncIterator[dict[str, str]]:
    """Frames from the bus, from ``last_id`` onwards, forever.

    Two filters that the subscription cannot apply for itself: the run,
    which is not part of an event's name, and the high-water mark that
    drops the events the replay already sent.

    ``overflowed`` is checked at the top of each turn rather than after
    each ``get``. The flag is only ever set while the queue is *full*, so
    a subscription that has overflowed always has something to deliver
    and always reaches this check before it blocks again; polling for it
    would buy nothing.
    """

    reported = False
    while True:
        if subscription.overflowed and not reported:
            reported = True
            yield _resync_frame(OVERFLOWED)
        event = await subscription.queue.get()
        if run_id is not None and event.run_id != run_id:
            continue
        if event.id is not None:
            if event.id <= last_id:
                continue
            last_id = event.id
        yield _live_frame(event)


async def _stream(
    settings: AthanoreSettings,
    store: Store | None,
    bus: EventBus | None,
    after: int,
    run_id: str | None,
    patterns: tuple[str, ...] | None,
) -> AsyncIterator[dict[str, str]]:
    """Replay, then live, with no gap and no duplicate between them.

    The subscription is taken first and closed on every exit — including
    the cancellation ``sse-starlette`` raises into this generator when
    the client disconnects, which is the only way a long-lived stream
    ever ends. A subscription that outlived its reader would keep the
    bus filling a queue nobody drains.
    """

    subscription = (
        None
        if bus is None
        else bus.subscribe(None if patterns is None else list(patterns))
    )
    try:
        last_id = after
        if store is not None:
            rows, capped = await _replay(
                store, after, settings.sse_replay_cap, run_id, patterns
            )
            if capped:
                yield _resync_frame(REPLAY_CAPPED)
            else:
                for row in rows:
                    last_id = row.id
                    yield _stored_frame(row)
        if subscription is None:
            # Nothing in this application can publish, so there is no
            # live half to switch to. Hold the connection open — the
            # keep-alive still says the server is up — until the client
            # goes away and the cancellation lands in `finally`.
            await asyncio.Event().wait()
        else:
            async for frame in _live(subscription, last_id, run_id):
                yield frame
    finally:
        if subscription is not None:
            subscription.close()


@router.get(
    "/events",
    summary="The event stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            # An empty media-type object: the wire is `text/event-stream`
            # and a frame's shape is per-line, not a JSON body, so there
            # is no schema to publish that would not be a fiction.
            "content": {"text/event-stream": {}},
            "description": (
                "An SSE stream. Each message is `id: <event id>`, "
                "`event: <event name>`, `data: <EventEnvelope as JSON>`. "
                "Ephemeral events (`task.stream`) carry no `id:`, and the "
                "`resync` control frame — sent when the replay overran "
                "`sse_replay_cap` or the server dropped events for a slow "
                "reader — carries neither an `id:` nor an event envelope."
            ),
        }
    },
)
async def events(
    request: Request,
    after: Annotated[
        int | None,
        Query(
            ge=0,
            description=(
                "Replay stored events after this event id, then go live. "
                "Takes precedence over the `Last-Event-ID` header."
            ),
        ),
    ] = None,
    run: Annotated[str | None, Query(description="Only events of this run.")] = None,
    names: Annotated[
        str | None,
        Query(
            description=(
                "Comma-separated event-name globs; a `*` matches one dotted "
                "segment, so `run.*` selects `run.created`. Omitted means "
                "every event."
            )
        ),
    ] = None,
    last_event_id: Annotated[
        str | None,
        Header(description="A browser's reconnect cursor, set by EventSource."),
    ] = None,
) -> EventSourceResponse:
    """Missed history, then live events, on one connection.

    `access_token` is accepted here as a query parameter and on no other
    route, because a browser's `EventSource` cannot set a header (08
    §Authentication); the query string is never logged.
    """

    patterns = _patterns(names)
    cursor = _cursor(after, last_event_id)
    settings: AthanoreSettings = request.app.state.settings
    store: Store | None = request.app.state.store
    return EventSourceResponse(
        _stream(settings, store, _bus(request), cursor, run, patterns),
        ping=15,
        # `sse-starlette` sets this itself; saying it here keeps the
        # reason with the endpoint. A buffering reverse proxy would hold
        # every frame back until the stream ended, which for this stream
        # is never.
        headers={"X-Accel-Buffering": "no"},
    )
