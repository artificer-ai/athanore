"""The programmatic host (T051, 04 §Programmatic host).

The subject is the wiring and the two refusals, so these tests start real
servers on real sockets: an ASGI transport would answer every request in
this file without ever binding a port, which is precisely the half that
can be wrong.

Every server here binds ``port=0`` and every settings object pins
``root_path`` to ``tmp_path``, so a suite run in parallel with a real
Athanore — or in a container whose shell exports ``ATHANORE_*`` — cannot
collide with one and cannot read the developer's own token file.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from sse_starlette.sse import AppStatus

from athanore.api.deps import MissingOperatorToken
from athanore.engine import Pool
from athanore.graph import GraphError
from athanore.plugins.registry import BUILTIN_WORKFLOW
from athanore.server import AthanoreServer, Server, V0Database
from athanore.settings import AthanoreSettings
from athanore.workflow import Workflow

#: The committed MVP database of T018, used by the v0 refusal.
V0_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "v0" / "mvp_small.sqlite3"


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """Undo the `configure_logging` every `Server.start()` performs.

    The handler it installs binds to whatever `sys.stderr` is at the
    moment it is built, and pytest swaps that stream between phases; left
    in place, the next test's logging would write to a closed file. The
    same fixture `tests/api/test_auth.py` keeps, for the same reason.
    """

    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


def build_workflow(name: str = "demo") -> Workflow:
    """One node, which is all a host has to register."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only():
        """Do nothing, successfully."""
        return None

    return wf


def make_settings(tmp_path: Path, **overrides: Any) -> AthanoreSettings:
    """Settings for a server that owns `tmp_path` and picks its own port."""

    fields: dict[str, Any] = {
        "root_path": tmp_path,
        "db_url": f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}",
        "host": "127.0.0.1",
        "port": 0,
    }
    fields.update(overrides)
    return AthanoreSettings(**fields)


# -- registration -----------------------------------------------------------


def test_a_reserved_name_is_rejected(tmp_path: Path) -> None:
    """A workflow called `ls` could never be submitted by name (11 §Verbs)."""

    server = Server(make_settings(tmp_path))
    with pytest.raises(GraphError, match="is a CLI verb"):
        server.register(build_workflow("ls"))
    assert server.workflows == {}
    assert server.engine.graphs == {}


def test_a_name_that_is_a_pool_is_rejected(tmp_path: Path) -> None:
    """Pool names and workflow names share one namespace (04 §Pools)."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow("first"), Pool("local", 1))
    with pytest.raises(GraphError, match="already the name of a pool"):
        server.register(build_workflow("local"))


def test_registering_a_name_twice_is_rejected(tmp_path: Path) -> None:
    """The second graph would be the one no attempt in flight is running."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow())
    with pytest.raises(GraphError, match="already registered"):
        server.register(build_workflow())


def test_register_finalizes_and_reaches_the_engine(tmp_path: Path) -> None:
    """The engine runs the same `Graph` object the workflow froze."""

    server = Server(make_settings(tmp_path))
    wf = build_workflow()
    assert server.register(wf, Pool("local", 2)) is server
    assert server.engine.graphs["demo"] is wf.graph
    assert server.engine.snapshot()["local"]["capacity"] == 2


def test_a_declaration_that_cannot_work_is_refused_at_registration(
    tmp_path: Path,
) -> None:
    """`collect` + `validate` run here, not at mount time (09)."""

    wf = build_workflow()
    wf.panel("nope", slot="run", kind="table", node="absent", source="/x")
    with pytest.raises(Exception, match="absent"):
        Server(make_settings(tmp_path)).register(wf)


# -- serving ----------------------------------------------------------------


async def test_port_zero_picks_a_free_port_and_url_reports_it(
    tmp_path: Path,
) -> None:
    """`url` is where the server actually is, which is the point of port 0."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow())
    await server.start()
    try:
        assert server.port != 0
        assert server.url == f"http://127.0.0.1:{server.port}"
        async with httpx.AsyncClient(base_url=server.url) as http:
            health = await http.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert body["ok"] is True
        assert body["pools"] == {"default": {"capacity": 1, "in_flight": 0}}
        # And the port agents are told about is the one that was bound,
        # not the placeholder the settings derived (12 §S6).
        assert server.settings.public_url == server.url
        assert server.settings.port == server.port
    finally:
        await server.stop()


async def test_an_explicit_public_url_is_left_alone(tmp_path: Path) -> None:
    """An operator's `public_url` is theirs — a container's, a proxy's."""

    settings = make_settings(tmp_path, public_url="https://athanore.example")
    server = Server(settings)
    await server.start()
    try:
        assert server.settings.public_url == "https://athanore.example"
    finally:
        await server.stop()


async def test_start_and_stop_twice_in_one_loop(tmp_path: Path) -> None:
    """A server that cannot restart breaks every test that follows it."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow())
    ports: list[int] = []
    for _ in range(2):
        await server.start()
        ports.append(server.port)
        async with httpx.AsyncClient(base_url=server.url) as http:
            assert (await http.get("/api/health")).status_code == 200
        await server.stop()
        assert server.app is None
    # Two live sockets, one after the other, on the same store — and the
    # second is the port the first was given: an ephemeral bind is
    # adopted into the settings, so a restart keeps the URL it published.
    assert ports[0] != 0
    assert ports[0] == ports[1]


async def test_a_restarted_server_serves_the_event_stream_again(
    tmp_path: Path,
) -> None:
    """`sse-starlette`'s shutdown flag is global, so a start has to clear it.

    `AppStatus.should_exit` is a **class attribute**, and once it is true
    every `EventSourceResponse` built afterwards ends the moment it
    opens. The library sets it from a watcher it runs for the length of
    each open stream, which polls the uvicorn server it finds on the
    SIGTERM handler — and `Server._stop_http` sets that server's
    `should_exit` to ask for the graceful shutdown of 04 §Shutdown. So a
    server stopped with a stream open leaves the flag set and the *next*
    server in the process has no event feed at all.

    The flag is set here rather than raced for, because what is under
    test is the clearing and not the library's polling interval: whatever
    set it, a started server serves streams.
    """

    server = Server(make_settings(tmp_path))
    server.register(build_workflow())
    await server.start()
    try:
        await assert_stream_is_live(server)
        await server.stop()
        # What a stop with a stream open leaves behind.
        AppStatus.should_exit = True
        await server.start()
        await assert_stream_is_live(server)
    finally:
        await server.stop()


async def assert_stream_is_live(server: Server) -> None:
    """Open `GET /api/events` and check it is still there a moment later.

    A stream that ended early is not a failed request — it is a 200 with
    nothing after the headers — so the assertion is that the endpoint
    subscribed to the bus, which its generator does before it replays.
    """

    async with httpx.AsyncClient(base_url=server.url, timeout=30.0) as http:
        async with http.stream("GET", "/api/events") as stream:
            assert stream.status_code == 200
            deadline = time.monotonic() + 10.0
            while not server.bus.subscriptions:
                assert time.monotonic() < deadline, "the event stream never subscribed"
                await asyncio.sleep(0.02)


async def test_starting_twice_is_refused(tmp_path: Path) -> None:
    """The second bind would put a second port on one engine."""

    server = Server(make_settings(tmp_path))
    await server.start()
    try:
        with pytest.raises(RuntimeError, match="already started"):
            await server.start()
    finally:
        await server.stop()


async def test_stop_is_safe_on_a_server_that_never_started(
    tmp_path: Path,
) -> None:
    await Server(make_settings(tmp_path)).stop()


async def test_a_bind_that_fails_leaves_nothing_running(tmp_path: Path) -> None:
    """A start that got half way takes itself back down.

    uvicorn answers a taken port by logging the `OSError` and exiting the
    process; a library has to raise instead, and it has to leave no
    dispatch loop claiming against a store nothing is serving.
    """

    first = Server(make_settings(tmp_path))
    await first.start()
    second = Server(
        make_settings(
            tmp_path,
            port=first.port,
            db_url=f"sqlite+aiosqlite:///{tmp_path / 'second.db'}",
        )
    )
    try:
        with pytest.raises(OSError, match="failed to bind"):
            await second.start()
        assert second.app is None
        assert not second.engine.scheduler.running
    finally:
        await first.stop()


async def test_the_builtin_panes_are_mounted_in_front(tmp_path: Path) -> None:
    """`with_builtins` is the composition root's job (09 §Mounting, D140)."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow())
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=server.url) as http:
            manifest = await http.get("/api/plugins")
        assert manifest.status_code == 200
        entries = manifest.json()
        assert [entry["workflow"] for entry in entries] == [BUILTIN_WORKFLOW]
    finally:
        await server.stop()


async def test_the_registered_workflow_is_on_the_wire(tmp_path: Path) -> None:
    """A run submitted over HTTP reaches the engine this server built."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow())
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=server.url) as http:
            listed = await http.get("/api/workflows")
            created = await http.post(
                "/api/workflows/demo/runs", json={"title": "a run"}
            )
        assert [wf["name"] for wf in listed.json()] == ["demo"]
        assert created.status_code == 201
        assert created.json()["run_id"]
    finally:
        await server.stop()


async def test_the_database_is_migrated_on_start(tmp_path: Path) -> None:
    """`run_migrations` is on by default, and the file did not exist."""

    settings = make_settings(tmp_path)
    server = Server(settings)
    await server.start()
    await server.stop()
    tables = _table_names(tmp_path / "athanore.db")
    assert "alembic_version" in tables
    assert "runs" in tables


# -- the two refusals -------------------------------------------------------


async def test_a_non_loopback_bind_without_a_token_refuses_to_start(
    tmp_path: Path,
) -> None:
    """12 §Operator token: an API that could only ever answer 401."""

    server = Server(make_settings(tmp_path, host="0.0.0.0"))
    with pytest.raises(MissingOperatorToken):
        await server.start()
    # And it refused before it touched anything: no database was made,
    # so a misconfigured start leaves nothing behind to clean up.
    assert not (tmp_path / "athanore.db").exists()
    await server.stop()


async def test_a_non_loopback_bind_with_a_token_starts(tmp_path: Path) -> None:
    """The refusal is about the missing token, not about the address."""

    server = Server(make_settings(tmp_path, host="0.0.0.0", operator_token="s3cret"))
    await server.start()
    try:
        assert server.url == f"http://127.0.0.1:{server.port}"
        async with httpx.AsyncClient(base_url=server.url) as http:
            assert (await http.get("/api/health")).status_code == 200
    finally:
        await server.stop()


async def test_a_v0_database_is_refused_with_the_import_hint(
    tmp_path: Path,
) -> None:
    """07 §Importing a v0 database: the one-way door, never a migration."""

    db = tmp_path / "athanore.db"
    shutil.copy(V0_FIXTURE, db)
    before = _table_names(db)

    server = Server(make_settings(tmp_path))
    with pytest.raises(V0Database) as raised:
        await server.start()
    message = str(raised.value)
    assert "athanore db import-v0" in message
    assert str(db) in message
    # Refused, not migrated: no v1 table was created, nothing was
    # stamped, and the MVP's rows are where they were. The schema rather
    # than the bytes, because asking the question opens the file and
    # SQLite's own pragmas can rewrite its journal-mode header — a
    # connection is not a migration, and the schema is what "migrated in
    # place" would have changed.
    assert _table_names(db) == before
    assert "alembic_version" not in before
    assert _row_count(db, "runs") > 0
    await server.stop()


# -- the shorthand ----------------------------------------------------------


def test_wf_run_serves_the_workflow_and_stops(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`wf.run()` is "build a `Server`, register this, serve" (04).

    In a thread, because `serve()` owns an event loop and blocks. The
    subclass is how the test reaches the server the shorthand built —
    `Workflow.run` imports `Server` from this module at call time, which
    is what makes the shorthand a thing a host can substitute.
    """

    import athanore.server as server_module

    built: list[Server] = []

    class Recording(server_module.Server):
        def __init__(self, settings: AthanoreSettings | None = None) -> None:
            super().__init__(settings)
            built.append(self)

    monkeypatch.setattr(server_module, "Server", Recording)

    wf = build_workflow("shorthand")
    thread = threading.Thread(
        target=wf.run,
        kwargs={
            "root_path": tmp_path,
            "db_url": f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}",
            "host": "127.0.0.1",
            "port": 0,
        },
        name="wf.run",
        daemon=True,
    )
    thread.start()
    try:
        server = _await_serving(built)
        assert list(server.workflows) == ["shorthand"]
        with httpx.Client(base_url=server.url) as http:
            assert http.get("/api/health").status_code == 200
    finally:
        for server in built:
            server.request_stop()
        thread.join(timeout=30)
    assert not thread.is_alive()


def test_serve_hands_the_bound_url_to_on_start(tmp_path: Path) -> None:
    """The callback `athanore serve` prints its URL from (T053, 11 §Server).

    On `port=0` the bound port exists only once uvicorn is listening, and
    `serve()` blocks from then on, so this is the one moment a caller can
    be told. The callback stops the server it was handed, which is what
    makes the test finite without a second thread.
    """

    server = Server(make_settings(tmp_path))
    seen: list[str] = []

    def announced(started: Server) -> None:
        # On the server's own event loop, so it says its piece and asks
        # for the stop rather than talking to the server it is inside.
        seen.append(started.url)
        started.request_stop()

    server.serve(on_start=announced)

    # The bound port, not the 0 that was asked for: the callback runs
    # after `_adopt_bound_port`, which is the whole reason it exists.
    assert seen == [f"http://127.0.0.1:{server.port}"]
    assert server.port != 0


def test_a_callback_that_raises_stops_the_server(tmp_path: Path) -> None:
    """A server nobody could be told about does not stay up."""

    server = Server(make_settings(tmp_path))

    def announced(started: Server) -> None:
        raise RuntimeError("nowhere to say it")

    with pytest.raises(RuntimeError, match="nowhere to say it"):
        server.serve(on_start=announced)
    assert "stopped" in repr(server)


def test_the_deprecated_alias_is_the_same_class() -> None:
    """`AthanoreServer` for one minor version (14 §Compatibility)."""

    assert AthanoreServer is Server


# -- helpers ----------------------------------------------------------------


def _table_names(path: Path) -> set[str]:
    """Every table in the SQLite file at ``path``."""

    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {name for (name,) in rows}
    finally:
        connection.close()


def _row_count(path: Path, table: str) -> int:
    """How many rows the SQLite file at ``path`` holds in ``table``."""

    connection = sqlite3.connect(path)
    try:
        ((count,),) = connection.execute(f"SELECT count(*) FROM {table}")
        return int(count)
    finally:
        connection.close()


def _await_serving(built: list[Server], timeout: float = 30.0) -> Server:
    """The server the thread built, once it is answering.

    Polled rather than signalled: the shorthand takes no callback, which
    is the whole of its interface, so a caller outside the loop learns it
    is up the same way any other client does.
    """

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if built and built[0].port != 0:
            server = built[0]
            with httpx.Client(base_url=server.url, timeout=1.0) as http:
                try:
                    if http.get("/api/health").status_code == 200:
                        return server
                except httpx.HTTPError:
                    pass
        time.sleep(0.05)
    raise AssertionError("wf.run() did not start serving")
