"""``GET /api/events``: replay, live, and the seam between them (08 §Events).

The endpoint is a long-lived response, which `httpx.ASGITransport` cannot
drive: it runs the application to completion and only then hands back a
body, so a stream that never ends is a test that never returns. These
tests therefore speak ASGI to the application directly —
:class:`Stream` is thirty lines of `receive`/`send` — which is also what
lets them assert the two things the wire cares about and a buffered body
would hide: that a frame arrives *before* the next one is published, and
that `task.stream` carries no `id:` line.

The boundary test is the one that matters. It commits an event *while the
replay query is in flight*, which is the only moment at which an event
can be both in the replayed page and on the subscription queue, and then
asserts the client saw it exactly once.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Iterable, MutableMapping
from pathlib import Path
from types import TracebackType
from typing import Any
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.pool import QueuePool

from athanore.api.app import create_app
from athanore.api.sse import OVERFLOWED, REPLAY_CAPPED, RESYNC
from athanore.engine import Engine
from athanore.events.bus import EventBus, Subscription
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.settings import AthanoreSettings
from athanore.store.clock import now
from athanore.store.repos.events import EventRepo
from athanore.store.uow import Store

#: How long any single wait in this suite may take. Every wait is on an
#: in-process event loop with no I/O, so a second is generous; what it
#: buys is a failed assertion instead of a hung suite.
TIMEOUT = 2.0

#: The token the auth tests present.
TOKEN = "s" * 32


# --------------------------------------------------------------------------
# The ASGI stream harness
# --------------------------------------------------------------------------


class StreamClosed(RuntimeError):
    """The response ended while a test was waiting for another frame."""


class Stream:
    """One in-flight ``text/event-stream`` response, read frame by frame.

    Enter it to send the request and wait for the response head; read it
    with :meth:`frame`; leaving it sends ``http.disconnect``, which is
    what `sse-starlette` cancels the generator on and therefore what
    exercises the endpoint's cleanup.
    """

    def __init__(
        self, app: FastAPI, url: str, headers: dict[str, str] | None = None
    ) -> None:
        self._app = app
        self._url = url
        self._request_headers = headers or {}
        self._chunks: asyncio.Queue[bytes] = asyncio.Queue()
        self._head = asyncio.Event()
        self._disconnect = asyncio.Event()
        self._request_sent = False
        self._buffer = b""
        self._task: asyncio.Task[None] | None = None
        self.status = 0
        self.headers: dict[str, str] = {}

    async def __aenter__(self) -> Stream:
        self._task = asyncio.create_task(self._run())
        await asyncio.wait_for(self._head.wait(), TIMEOUT)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self._disconnect.set()
        assert self._task is not None
        try:
            await asyncio.wait_for(self._task, TIMEOUT)
        except TimeoutError:  # pragma: no cover - a hung endpoint is a bug
            self._task.cancel()
            raise

    async def _run(self) -> None:
        url = urlsplit(self._url)
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": url.path,
            "raw_path": url.path.encode(),
            "query_string": url.query.encode(),
            "root_path": "",
            "headers": [
                (key.lower().encode(), value.encode())
                for key, value in {
                    "host": "testserver",
                    **self._request_headers,
                }.items()
            ],
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 50000),
        }
        try:
            await self._app(scope, self._receive, self._send)
        finally:
            # Whatever happened — a clean end, a refusal, an exception —
            # nothing may still be waiting for a head that is not coming.
            self._head.set()

    async def _receive(self) -> dict[str, Any]:
        if not self._request_sent:
            self._request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message: MutableMapping[str, Any]) -> None:
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = {
                key.decode().lower(): value.decode()
                for key, value in message.get("headers", [])
            }
            self._head.set()
        elif message["type"] == "http.response.body":
            body = message.get("body", b"")
            if body:
                await self._chunks.put(body)

    async def body(self) -> bytes:
        """Everything the response sent, once it has ended.

        For the refusals, which are ordinary JSON responses.
        """

        assert self._task is not None
        self._disconnect.set()
        await asyncio.wait_for(self._task, TIMEOUT)
        parts = []
        while not self._chunks.empty():
            parts.append(self._chunks.get_nowait())
        return b"".join(parts)

    async def frame(self, within: float = TIMEOUT) -> dict[str, str]:
        """The next SSE message, keep-alive comments skipped."""

        while True:
            message = self._take()
            if message is not None:
                return message
            try:
                self._buffer += await asyncio.wait_for(self._chunks.get(), within)
            except TimeoutError:
                assert self._task is not None
                if self._task.done():
                    raise StreamClosed("the response ended") from None
                raise

    async def frames(self, count: int) -> list[dict[str, str]]:
        """The next ``count`` messages, in order."""

        return [await self.frame() for _ in range(count)]

    async def until(
        self, predicate: Callable[[dict[str, str]], bool]
    ) -> list[dict[str, str]]:
        """Every message up to and including the first ``predicate`` accepts."""

        collected: list[dict[str, str]] = []
        while True:
            collected.append(await self.frame())
            if predicate(collected[-1]):
                return collected

    async def silent(self, seconds: float = 0.05) -> None:
        """Assert nothing more arrives within ``seconds``."""

        with pytest.raises(TimeoutError):
            await self.frame(within=seconds)

    def _take(self) -> dict[str, str] | None:
        """One parsed message off the buffer, or ``None`` if it holds none."""

        while True:
            head, separator, rest = self._buffer.partition(b"\r\n\r\n")
            if not separator:
                return None
            self._buffer = rest
            message = _parse(head.decode("utf-8"))
            if message:
                return message
            # A keep-alive is a comment and nothing else; skip it and
            # look at what follows in the same buffer.


def _parse(block: str) -> dict[str, str]:
    """One SSE message's fields; ``data`` lines joined, comments dropped."""

    fields: dict[str, str] = {}
    data: list[str] = []
    for line in block.split("\r\n"):
        if not line or line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if name == "data":
            data.append(value)
        else:
            fields[name] = value
    if data:
        fields["data"] = "\n".join(data)
    return fields


def payload(frame: dict[str, str]) -> dict[str, Any]:
    """The ``data:`` line of ``frame``, decoded."""

    decoded: dict[str, Any] = json.loads(frame["data"])
    return decoded


def ids(frames: Iterable[dict[str, str]]) -> list[str | None]:
    """The ``id:`` of each frame, ``None`` where there was none."""

    return [frame.get("id") for frame in frames]


async def settled(engine: AsyncEngine) -> None:
    """Wait until the connection pool has nothing checked out.

    Polled rather than awaited, and ASYNC110 is silenced for it: the read
    that holds the connection is deliberately detached from the request
    that started it (`athanore.api.sse._replay`), so there is no event to
    wait on. The loop is bounded by :data:`TIMEOUT`.
    """

    pool = engine.pool
    assert isinstance(pool, QueuePool), "this store is not pooled; nothing to check"
    deadline = asyncio.get_running_loop().time() + TIMEOUT
    while (  # noqa: ASYNC110 - nothing to await on; see the docstring
        pool.checkedout() and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)
    assert pool.checkedout() == 0, "a pooled connection was never returned"


# --------------------------------------------------------------------------
# Fixtures and helpers
# --------------------------------------------------------------------------


@pytest.fixture
def capped_settings(tmp_path: Path, db_url: str) -> Callable[[int], AthanoreSettings]:
    """Settings identical to the suite's, with a chosen replay cap."""

    def build(cap: int) -> AthanoreSettings:
        return AthanoreSettings(
            root_path=tmp_path,
            db_url=db_url,
            public_url="http://127.0.0.1:4002",
            workers=1,
            sse_replay_cap=cap,
        )

    return build


async def commit(
    store: Store,
    name: EventName = EventName.run_created,
    run_id: str = "RUN1",
    **data: Any,
) -> Event:
    """Store one event and publish it: the real outbox path (07 §Outbox)."""

    event = Event(
        run_id=run_id,
        name=name.value,
        data=data or _sample(name),
        created=now(),
    )
    async with store.uow() as uow:
        uow.emit(event)
    return event


def _sample(name: EventName) -> dict[str, Any]:
    """A payload 18 accepts for the handful of names these tests emit."""

    return {
        EventName.run_created: {
            "workflow": "demo",
            "title": "a run",
            "position": 0,
        },
        EventName.run_paused: {},
        EventName.task_enqueued: {
            "node": "start",
            "attempt": 1,
            "reason": "transition",
            "payload_present": False,
            "branch": [],
        },
        EventName.task_stream: {"seq_from": 0, "seq_to": 3},
    }[name]


def ephemeral(task_id: int, run_id: str = "RUN1") -> Event:
    """A ``task.stream`` event: published, never stored (03)."""

    return Event(
        run_id=run_id,
        task_id=task_id,
        name=EventName.task_stream.value,
        data={"seq_from": 0, "seq_to": 3},
        created=now(),
    )


# --------------------------------------------------------------------------
# Replay, then live
# --------------------------------------------------------------------------


async def test_the_stream_replays_history_and_then_goes_live(
    app: FastAPI, store: Store
) -> None:
    """One connection, two halves, one ascending sequence of ids."""

    first = await commit(store)
    second = await commit(store, EventName.run_paused)

    async with Stream(app, "/api/events?after=0") as stream:
        assert stream.status == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        replayed = await stream.frames(2)
        third = await commit(store, EventName.task_enqueued)
        live = await stream.frame()

    assert ids(replayed) == [str(first.id), str(second.id)]
    assert [frame["event"] for frame in replayed] == [
        EventName.run_created.value,
        EventName.run_paused.value,
    ]
    assert live["id"] == str(third.id)
    assert live["event"] == EventName.task_enqueued.value
    assert payload(live)["data"]["node"] == "start"
    assert payload(live)["data"]["reason"] == "transition"


async def test_a_cursor_replays_only_what_follows_it(
    app: FastAPI, store: Store
) -> None:
    """`after` is exclusive: the client already has that event."""

    first = await commit(store)
    second = await commit(store, EventName.run_paused)

    async with Stream(app, f"/api/events?after={first.id}") as stream:
        frame = await stream.frame()
        await stream.silent()

    assert frame["id"] == str(second.id)


async def test_the_last_event_id_header_is_the_cursor_on_reconnect(
    app: FastAPI, store: Store
) -> None:
    """A browser sets the header by itself; `after` need not be in the URL."""

    first = await commit(store)
    second = await commit(store, EventName.run_paused)

    async with Stream(
        app, "/api/events", headers={"Last-Event-ID": str(first.id)}
    ) as stream:
        frame = await stream.frame()
        await stream.silent()

    assert frame["id"] == str(second.id)


async def test_the_query_parameter_beats_the_header(app: FastAPI, store: Store) -> None:
    """Both present is not ambiguous: `after` is what the client meant."""

    first = await commit(store)
    second = await commit(store, EventName.run_paused)

    async with Stream(
        app,
        f"/api/events?after={first.id}",
        headers={"Last-Event-ID": "0"},
    ) as stream:
        frame = await stream.frame()
        await stream.silent()

    assert frame["id"] == str(second.id)


async def test_a_last_event_id_that_is_not_an_event_id_is_refused(
    app: FastAPI,
) -> None:
    """A cursor a client made up is a 422, not a silent replay of everything."""

    async with Stream(
        app, "/api/events", headers={"Last-Event-ID": "not-an-id"}
    ) as stream:
        assert stream.status == 422
        body = json.loads(await stream.body())

    assert body["code"] == "validation"
    assert body["errors"][0]["loc"] == ["header", "last-event-id"]


# --------------------------------------------------------------------------
# The boundary
# --------------------------------------------------------------------------


async def test_an_event_committed_during_the_replay_is_sent_exactly_once(
    app: FastAPI, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seam: in the replayed page *and* on the queue, sent once.

    The subscription is taken before the replay query, so an event that
    commits while that query is in flight is on the queue and in its
    result. That is the overlap the endpoint exists to handle, and the
    only way to create it is to commit inside the query — which is what
    the patched `list_after` does.
    """

    first = await commit(store)
    original = EventRepo.list_after
    during: list[Event] = []
    raced = asyncio.Event()

    async def racing(
        self: EventRepo, after: int, limit: int, *args: Any, **kwargs: Any
    ) -> Any:
        if not during:
            during.append(await commit(store, EventName.run_paused))
            raced.set()
        return await original(self, after, limit, *args, **kwargs)

    monkeypatch.setattr(EventRepo, "list_after", racing)

    async with Stream(app, "/api/events?after=0") as stream:
        # The commit below must follow the raced one, so that the three
        # ids are the three cases in order: replayed only, replayed *and*
        # queued, queued only.
        await asyncio.wait_for(raced.wait(), TIMEOUT)
        after = await commit(store, EventName.task_enqueued)
        seen = await stream.until(lambda frame: frame.get("id") == str(after.id))
        await stream.silent()

    assert during, "the replay never ran, so nothing raced it"
    assert ids(seen) == [str(first.id), str(during[0].id), str(after.id)]


async def test_a_disconnect_during_the_replay_returns_the_connection(
    app: FastAPI,
    store: Store,
    sa_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tab closed mid-replay must not cost the pool a connection.

    The head is sent before the first frame, so a client that gives up
    the moment it arrives is disconnecting while the replay query is
    still in flight — which is where cancellation would otherwise land
    inside the connection's own `close`. The gate below holds the query
    open until the disconnect has been delivered, so the race is the
    test rather than a matter of scheduling luck.
    """

    await commit(store)
    original = EventRepo.list_after
    entered = asyncio.Event()
    release = asyncio.Event()

    async def gated(self: EventRepo, *args: Any, **kwargs: Any) -> Any:
        entered.set()
        await release.wait()
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(EventRepo, "list_after", gated)

    stream = Stream(app, "/api/events?after=0")
    await stream.__aenter__()
    await asyncio.wait_for(entered.wait(), TIMEOUT)
    closing = asyncio.create_task(stream.__aexit__(None, None, None))
    await asyncio.sleep(0)
    release.set()
    await asyncio.wait_for(closing, TIMEOUT)

    await settled(sa_engine)


async def test_the_subscription_is_closed_when_the_client_disconnects(
    app: FastAPI, bus: EventBus, store: Store
) -> None:
    """A subscription that outlived its reader would fill a queue forever."""

    async with Stream(app, "/api/events") as stream:
        await commit(store)
        await stream.frame()
        assert len(bus.subscriptions) == 1

    assert bus.subscriptions == ()


# --------------------------------------------------------------------------
# Filters
# --------------------------------------------------------------------------


async def test_names_filters_both_halves_of_the_stream(
    app: FastAPI, store: Store
) -> None:
    """`run.*` selects `run.created` and leaves `task.enqueued` behind."""

    kept = await commit(store)
    await commit(store, EventName.task_enqueued)

    async with Stream(app, "/api/events?after=0&names=run.*") as stream:
        replayed = await stream.frame()
        await commit(store, EventName.task_enqueued)
        live_kept = await commit(store, EventName.run_paused)
        live = await stream.frame()
        await stream.silent()

    assert replayed["id"] == str(kept.id)
    assert live["id"] == str(live_kept.id)
    assert live["event"] == EventName.run_paused.value


async def test_the_run_filter_selects_one_run(app: FastAPI, store: Store) -> None:
    """`run` is not part of an event's name, so both halves filter on it."""

    mine = await commit(store, run_id="RUN1")
    await commit(store, run_id="RUN2")

    async with Stream(app, "/api/events?after=0&run=RUN1") as stream:
        replayed = await stream.frame()
        await commit(store, EventName.run_paused, run_id="RUN2")
        live_mine = await commit(store, EventName.run_paused, run_id="RUN1")
        live = await stream.frame()
        await stream.silent()

    assert replayed["id"] == str(mine.id)
    assert live["id"] == str(live_mine.id)


async def test_a_character_class_in_names_is_refused(app: FastAPI) -> None:
    """The store's glob has no `LIKE` equivalent for it (D87), so neither has this."""

    async with Stream(app, "/api/events?names=run.[ab]*") as stream:
        assert stream.status == 422
        body = json.loads(await stream.body())

    assert body["code"] == "validation"
    assert body["errors"][0]["loc"] == ["query", "names"]


async def test_an_empty_names_is_no_filter(app: FastAPI, store: Store) -> None:
    """ "Give me no names" is never what a caller means."""

    stored = await commit(store)

    async with Stream(app, "/api/events?after=0&names=") as stream:
        frame = await stream.frame()

    assert frame["id"] == str(stored.id)


# --------------------------------------------------------------------------
# Ephemeral events
# --------------------------------------------------------------------------


async def test_a_task_stream_frame_carries_no_id(app: FastAPI, store: Store) -> None:
    """`Last-Event-ID` must always name a row the store can replay from."""

    stored = await commit(store)

    async with Stream(app, "/api/events?after=0") as stream:
        assert (await stream.frame())["id"] == str(stored.id)
        await store.publish_ephemeral(ephemeral(task_id=7))
        frame = await stream.frame()

    assert "id" not in frame
    assert frame["event"] == EventName.task_stream.value
    body = payload(frame)
    assert body["task_id"] == 7
    assert body["data"] == {"seq_from": 0, "seq_to": 3}
    assert "id" not in body


async def test_an_ephemeral_event_does_not_move_the_cursor(
    app: FastAPI, store: Store
) -> None:
    """It has no id, so it can neither advance nor be dropped by one."""

    async with Stream(app, "/api/events") as stream:
        await store.publish_ephemeral(ephemeral(task_id=7))
        await stream.frame()
        stored = await commit(store)
        frame = await stream.frame()

    assert frame["id"] == str(stored.id)


# --------------------------------------------------------------------------
# resync
# --------------------------------------------------------------------------


async def test_a_replay_beyond_the_cap_sends_resync_instead_of_history(
    capped_settings: Callable[[int], AthanoreSettings],
    store: Store,
    bus: EventBus,
) -> None:
    """A truncated history the client would believe was complete is worse."""

    settings = capped_settings(2)
    app = create_app(
        settings=settings, engine=Engine(settings, store, bus), store=store
    )
    for _ in range(3):
        await commit(store)

    async with Stream(app, "/api/events?after=0") as stream:
        frame = await stream.frame()
        await stream.silent()
        live = await commit(store, EventName.run_paused)
        after = await stream.frame()

    assert frame == {"event": RESYNC, "data": json.dumps({"reason": REPLAY_CAPPED})}
    assert "id" not in frame
    assert after["id"] == str(live.id)


async def test_a_replay_exactly_at_the_cap_is_sent_whole(
    capped_settings: Callable[[int], AthanoreSettings],
    store: Store,
    bus: EventBus,
) -> None:
    """The cap is a maximum, not a threshold one short of itself."""

    settings = capped_settings(2)
    app = create_app(
        settings=settings, engine=Engine(settings, store, bus), store=store
    )
    first = await commit(store)
    second = await commit(store, EventName.run_paused)

    async with Stream(app, "/api/events?after=0") as stream:
        replayed = await stream.frames(2)
        await stream.silent()

    assert ids(replayed) == [str(first.id), str(second.id)]


async def test_an_overflowed_subscription_sends_resync_once(
    app: FastAPI, bus: EventBus, store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bus drops rather than stalling every writer (D29); the hole is told."""

    subscribe = EventBus.subscribe

    def shallow(
        self: EventBus, patterns: list[str] | None = None, *, maxsize: int = 0
    ) -> Subscription:
        return subscribe(self, patterns, maxsize=2)

    monkeypatch.setattr(EventBus, "subscribe", shallow)

    async with Stream(app, "/api/events") as stream:
        # One synchronous burst: `publish` never awaits, so the reader
        # cannot drain between puts and the queue really does overflow.
        for index in range(5):
            bus.publish(
                Event(
                    run_id="RUN1",
                    name=EventName.run_created.value,
                    data={"workflow": "demo", "title": f"run {index}", "position": 0},
                    created=now(),
                )
            )
        seen = await stream.until(lambda frame: frame["event"] == RESYNC)
        assert json.loads(seen[-1]["data"]) == {"reason": OVERFLOWED}

        # Sticky, but reported once: a second resync per event afterwards
        # would be a storm, not a signal.
        stored = await commit(store)
        rest = await stream.until(lambda frame: frame.get("id") == str(stored.id))
        await stream.silent()

    assert [frame["event"] for frame in rest].count(RESYNC) == 0


# --------------------------------------------------------------------------
# Headers, auth and the collaborator-less application
# --------------------------------------------------------------------------


async def test_the_stream_refuses_proxy_buffering(app: FastAPI) -> None:
    """A buffering proxy would hold every frame until a stream that never ends."""

    async with Stream(app, "/api/events") as stream:
        assert stream.headers["x-accel-buffering"] == "no"
        assert stream.headers["cache-control"] == "no-store"


async def test_a_loopback_bind_streams_without_a_credential(
    app: FastAPI, store: Store
) -> None:
    """The default deployment sees no login at all (12 §Posture)."""

    stored = await commit(store)

    async with Stream(app, "/api/events?after=0") as stream:
        assert stream.status == 200
        assert (await stream.frame())["id"] == str(stored.id)


async def test_the_access_token_query_parameter_is_accepted_when_auth_is_on(
    tmp_path: Path, db_url: str, store: Store, bus: EventBus
) -> None:
    """`EventSource` cannot set a header, so this route takes a query (08)."""

    settings = AthanoreSettings(
        root_path=tmp_path,
        db_url=db_url,
        host="0.0.0.0",
        operator_token=SecretStr(TOKEN),
        workers=1,
    )
    app = create_app(
        settings=settings, engine=Engine(settings, store, bus), store=store
    )
    stored = await commit(store)

    async with Stream(app, f"/api/events?after=0&access_token={TOKEN}") as opened:
        assert opened.status == 200
        assert (await opened.frame())["id"] == str(stored.id)

    async with Stream(app, "/api/events?access_token=wrong") as refused:
        assert refused.status == 401
        assert json.loads(await refused.body())["code"] == "unauthorized"

    async with Stream(app, "/api/events") as bare:
        assert bare.status == 401


async def test_an_application_with_no_collaborators_still_opens_a_stream(
    tmp_path: Path, db_url: str
) -> None:
    """Nothing here can publish, so the stream is honest and simply empty."""

    app = create_app(
        settings=AthanoreSettings(root_path=tmp_path, db_url=db_url, workers=1)
    )

    async with Stream(app, "/api/events") as stream:
        assert stream.status == 200
        await stream.silent()
