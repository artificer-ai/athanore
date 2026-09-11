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
import hashlib
import logging
import os
import shutil
import sqlite3
import stat
import sys
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
import structlog.testing
from sse_starlette.sse import AppStatus

from athanore.api.deps import MissingOperatorToken
from athanore.engine import Pool
from athanore.events.names import EventName
from athanore.graph import GraphError
from athanore.plugins.discovery import (
    LayoutError,
    LoadError,
    Registered,
    RemovedWorkflow,
    load_target,
)
from athanore.plugins.persist import PersistError
from athanore.plugins.registry import BUILTIN_WORKFLOW
from athanore.server import (
    AthanoreServer,
    ConfiguredRows,
    Server,
    Skipped,
    V0Database,
)
from athanore.settings import AthanoreSettings
from athanore.store.rows import EventRow, RunRow, RunStatus, TaskRow, TaskStatus
from athanore.workflow import Workflow
from tests.plugins.fixture_wf import fixture_workflow

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


# ==========================================================================
# Live registration (T085, 22 §Server surface, §Effects, §Persistence)
# ==========================================================================
#
# The three verbs on a *started* server, with bodies that park so an
# attempt is genuinely in flight when the verb runs. Every effect 22
# lists is read back from where it lands — the engine's registries, the
# application's routes and manifest, the events table, the toml file —
# and the `.py` files under `tmp_path` are hashed before and after every
# test in this module, because no verb may ever touch the source.

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 10.0


@pytest.fixture(autouse=True)
def sources_are_never_written(tmp_path: Path) -> Iterator[None]:
    """22 §Persistence, "Never the source": every `.py` is byte-identical."""

    def digests() -> dict[Path, str]:
        return {
            path: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(tmp_path.rglob("*.py"))
        }

    before = digests()
    yield
    after = digests()
    assert {p: h for p, h in after.items() if p in before} == before


class Parked:
    """A body that announces itself and then waits to be cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.starts = 0

    def workflow(self, name: str) -> Workflow:
        wf = Workflow(name)

        @wf.node(start=True)
        async def only() -> str:
            self.starts += 1
            self.started.set()
            await asyncio.sleep(3600)
            return "landed"  # pragma: no cover - the point is that it never does

        return wf


class Version:
    """One edition of a two-node workflow: `top` parks, then routes to `bottom`.

    Every body appends ``(node, tag)`` to a shared list, so which
    edition ran a node is a fact the test reads back.
    """

    def __init__(self, tag: str, marks: list[tuple[str, str]]) -> None:
        self.tag = tag
        self.marks = marks
        self.started = asyncio.Event()
        self.go = asyncio.Event()

    def workflow(self, name: str = "versioned") -> Workflow:
        wf = Workflow(name)
        tag, marks = self.tag, self.marks

        @wf.node(start=True)
        async def top(bottom):  # type: ignore[no-untyped-def]
            marks.append(("top", tag))
            self.started.set()
            await self.go.wait()
            return bottom

        @wf.node()
        async def bottom() -> str:
            marks.append(("bottom", tag))
            return "landed"

        return wf


async def wait_for(event: asyncio.Event) -> None:
    async with asyncio.timeout(DEADLINE):
        await event.wait()


async def wait_until(condition: Callable[[], Awaitable[bool]]) -> None:
    async with asyncio.timeout(DEADLINE):
        while not await condition():  # noqa: ASYNC110 - the store is what answers
            await asyncio.sleep(0.01)


async def stored_events(server: Server) -> list[EventRow]:
    async with server.store.reader() as reader:
        return list(await reader.events.list_after(0, 1000))


async def named_events(server: Server, *names: str) -> list[EventRow]:
    return [row for row in await stored_events(server) if row.name in names]


async def task_of(server: Server, run_id: str) -> TaskRow:
    async with server.store.reader() as reader:
        tasks = await reader.tasks.list_for_run(run_id)
    return tasks[0]


async def run_row(server: Server, run_id: str) -> RunRow:
    async with server.store.reader() as reader:
        row = await reader.runs.get(run_id)
    assert row is not None
    return row


async def manifest_order(server: Server) -> list[str]:
    async with httpx.AsyncClient(base_url=server.url) as http:
        response = await http.get("/api/plugins")
    assert response.status_code == 200, response.text
    return [entry["workflow"] for entry in response.json()]


async def plugin_route_status(server: Server, workflow: str) -> int:
    async with httpx.AsyncClient(base_url=server.url) as http:
        response = await http.get(f"/api/plugins/{workflow}/rules")
    return response.status_code


async def workflow_out(server: Server, name: str) -> dict[str, Any]:
    async with httpx.AsyncClient(base_url=server.url) as http:
        response = await http.get(f"/api/workflows/{name}")
    assert response.status_code == 200, response.text
    return response.json()


@asynccontextmanager
async def serving(server: Server) -> AsyncIterator[Server]:
    """`start()`, and `stop()` on the way out whatever the test did."""

    await server.start()
    try:
        yield server
    finally:
        await server.stop()


def write_target(tmp_path: Path, stem: str, name: str, node: str = "only") -> str:
    """A workflow file under `tmp_path`, and the target that names it."""

    path = tmp_path / f"{stem}.py"
    path.write_text(
        "from athanore.workflow import Workflow\n"
        "\n"
        f'wf = Workflow("{name}")\n'
        "\n"
        "\n"
        "@wf.node(start=True)\n"
        f"async def {node}():\n"
        "    return None\n"
    )
    return f"{path}:wf"


@pytest.fixture(autouse=True)
def restore_imports() -> Iterator[None]:
    """`load_target` on a file target edits `sys.modules` and `sys.path`."""

    path = list(sys.path)
    modules = set(sys.modules)
    yield
    sys.path[:] = path
    for name in set(sys.modules) - modules:
        del sys.modules[name]


# -- add ----------------------------------------------------------------------


async def test_add_mounts_the_plugin_surface_last(tmp_path: Path) -> None:
    """22 §Add step 2: routes answer, the manifest lists it after the rest."""

    server = Server(make_settings(tmp_path))
    server.register(fixture_workflow("first"))
    async with serving(server):
        assert await plugin_route_status(server, "second") == 404
        registered = await server.add(fixture_workflow("second"))
        assert registered == Registered("second", None)
        assert await plugin_route_status(server, "second") == 200
        assert await manifest_order(server) == [BUILTIN_WORKFLOW, "first", "second"]
        assert list(server.workflows) == ["first", "second"]
        assert server.engine.pools.for_workflow("second").name == "default"
        # And a run of it dispatches on this server.
        run = await server.engine.ops.submit("second", "a round")
        await wait_until(lambda: _run_is(server, run.id, RunStatus.completed))


async def test_add_recovers_the_names_orphaned_rows_and_emits_in_order(
    tmp_path: Path,
) -> None:
    """22 §Add step 3–4: a row a `remove` left `in_progress` is reset.

    The events table reads `workflow.unregistered`, then
    `engine.recovered`, then `workflow.registered` — recovery is step 3
    and the event step 4 (D247) — none with a `run_id`, and the reset
    row is claimed again by the new body.
    """

    first, second = Parked(), Parked()
    server = Server(make_settings(tmp_path))
    server.register(first.workflow("park"))
    async with serving(server):
        run = await server.engine.ops.submit("park", "a run")
        await wait_for(first.started)
        task = await task_of(server, run.id)

        removed = await server.remove("park")
        assert removed == RemovedWorkflow("park", (task.id,), None)
        assert (await task_of(server, run.id)).status is TaskStatus.in_progress
        assert "park" not in server.workflows
        assert "park" not in server.engine.graphs

        added = await server.add(second.workflow("park"))
        assert added.name == "park"
        await wait_for(second.started)
        assert second.starts == 1
        assert first.starts == 1

        rows = await named_events(
            server,
            EventName.workflow_unregistered,
            EventName.workflow_registered,
            EventName.engine_recovered,
        )
        assert [row.name for row in rows] == [
            EventName.workflow_unregistered,
            EventName.engine_recovered,
            EventName.workflow_registered,
        ]
        assert all(row.run_id is None for row in rows)
        assert rows[0].data == {"workflow": "park", "task_ids": [task.id]}
        assert rows[1].data == {"task_ids": [task.id]}
        assert rows[2].data == {"workflow": "park", "pool": "default"}


async def test_add_before_start_touches_only_the_registries(
    tmp_path: Path,
) -> None:
    """22 §Server surface: no application to mount into, no store to emit to."""

    server = Server(make_settings(tmp_path))
    wf = build_workflow("early")
    assert await server.add(wf, target="early.py:wf") == Registered("early", None)
    assert server.workflows == {"early": wf}
    assert server.targets == {"early": "early.py:wf"}
    assert "early" in server.engine.graphs
    assert await server.replace(build_workflow("early")) == Registered("early", None)
    assert await server.remove("early") == RemovedWorkflow("early", (), None)
    assert server.workflows == {}
    assert server.targets == {}
    assert "early" not in server.engine.graphs
    async with serving(server):
        assert await named_events(server, *[n for n in EventName]) == []


async def test_a_pool_object_creates_the_pool_before_start_only(
    tmp_path: Path,
) -> None:
    """D239: the boot-time idiom before `start()`; a name only while serving."""

    server = Server(make_settings(tmp_path))
    await server.add(build_workflow("boot"), Pool("fresh", 1))
    assert server.engine.snapshot()["fresh"]["capacity"] == 1
    async with serving(server):
        with pytest.raises(KeyError, match="no pool named 'later'"):
            await server.add(build_workflow("live"), Pool("later", 1))
        assert "live" not in server.workflows
        assert "later" not in server.engine.pools
        # An existing pool by object, as by name: bound, not resized.
        await server.add(build_workflow("live"), Pool("fresh", 9))
        assert server.engine.pools.for_workflow("live").name == "fresh"
        assert server.engine.snapshot()["fresh"]["capacity"] == 1
        await server.add(build_workflow("named"), "fresh")
        assert server.engine.pools.for_workflow("named").name == "fresh"


async def test_an_unknown_pool_name_is_a_key_error_naming_the_known(
    tmp_path: Path,
) -> None:
    server = Server(make_settings(tmp_path))
    server.register(build_workflow("first"), Pool("local", 1))
    async with serving(server):
        with pytest.raises(KeyError) as raised:
            await server.add(build_workflow("second"), "nope")
        assert "'nope'" in str(raised.value)
        assert "local" in str(raised.value)
        assert "second" not in server.workflows


async def test_a_mount_the_application_refuses_undoes_the_engine_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed `add` leaves the server exactly as it was."""

    from athanore.plugins import mount as mount_module

    server = Server(make_settings(tmp_path))
    async with serving(server):

        def refuse(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("the router cannot be built")

        monkeypatch.setattr(mount_module, "mount", refuse)
        with pytest.raises(RuntimeError, match="cannot be built"):
            await server.add(fixture_workflow("broken"))
        assert "broken" not in server.workflows
        assert "broken" not in server.targets
        assert "broken" not in server.engine.graphs
        assert await manifest_order(server) == [BUILTIN_WORKFLOW]
        assert await named_events(server, EventName.workflow_registered) == []


# -- replace -----------------------------------------------------------------


async def test_replace_swaps_the_graph_and_emits(tmp_path: Path) -> None:
    """22 §Replace: the attempt in flight finishes on the old body, the
    next task dispatches on the new graph, and `workflow.replaced` names
    the bound pool and the recorded target."""

    marks: list[tuple[str, str]] = []
    old, new = Version("old", marks), Version("new", marks)
    server = Server(make_settings(tmp_path))
    server.register(old.workflow(), Pool("play", 2), target="flows.py:v1")
    async with serving(server):
        run = await server.engine.ops.submit("versioned", "a run")
        await wait_for(old.started)

        registered = await server.replace(new.workflow(), target="flows.py:v2")
        assert registered == Registered("versioned", None)
        assert server.targets == {"versioned": "flows.py:v2"}
        assert server.engine.graphs["versioned"] is server.workflows["versioned"].graph

        (event,) = await named_events(server, EventName.workflow_replaced)
        assert event.run_id is None
        assert event.data == {
            "workflow": "versioned",
            "pool": "play",
            "target": "flows.py:v2",
        }

        # The parked attempt is still the old edition's, and finishes as it.
        old.go.set()
        await wait_until(lambda: _run_is(server, run.id, RunStatus.completed))
        assert ("top", "old") in marks
        # `bottom` was dispatched after the swap: the runner looked the
        # graph up by name at the claim, so the new edition ran it.
        assert ("bottom", "new") in marks
        assert ("bottom", "old") not in marks


async def test_replace_keeps_the_recorded_target_when_none_is_given(
    tmp_path: Path,
) -> None:
    """D240."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow("kept"), target="kept.py:wf")
    async with serving(server):
        await server.replace(build_workflow("kept"))
        assert server.targets == {"kept": "kept.py:wf"}
        (event,) = await named_events(server, EventName.workflow_replaced)
        assert event.data["target"] == "kept.py:wf"
        await server.replace(build_workflow("kept"), target="kept2.py:wf")
        assert server.targets == {"kept": "kept2.py:wf"}


async def test_replace_refuses_a_pool_move_with_attempts_in_flight(
    tmp_path: Path,
) -> None:
    """22 §Pools: `ValueError`, and nothing changed — not even the toml."""

    parked = Parked()
    server = Server(make_settings(tmp_path))
    server.register(parked.workflow("park"), Pool("one", 1), target="p.py:wf")
    server.register(build_workflow("other"), Pool("two", 1))
    toml = tmp_path / "athanore.toml"
    async with serving(server):
        await server.engine.ops.submit("park", "a run")
        await wait_for(parked.started)
        before = server.workflows["park"]
        with pytest.raises(ValueError, match="attempts in flight"):
            await server.replace(
                build_workflow("park"), "two", target="p2.py:wf", persist=True
            )
        assert server.workflows["park"] is before
        assert server.targets["park"] == "p.py:wf"
        assert server.engine.pools.for_workflow("park").name == "one"
        assert not toml.exists()
        assert await named_events(server, EventName.workflow_replaced) == []
        # Without attempts in flight the same move is accepted.
        await server.replace(build_workflow("other"), "one")
        assert server.engine.pools.for_workflow("other").name == "one"


async def test_replace_swaps_the_plugin_surface_in_place(tmp_path: Path) -> None:
    """22 §Replace step 2: same position in the manifest."""

    server = Server(make_settings(tmp_path))
    server.register(fixture_workflow("a"))
    server.register(fixture_workflow("b"))
    server.register(fixture_workflow("c"))
    async with serving(server):
        await server.replace(fixture_workflow("b"))
        assert await manifest_order(server) == [BUILTIN_WORKFLOW, "a", "b", "c"]
        assert await plugin_route_status(server, "b") == 200
        # Replaced by an edition that declares nothing: the entry goes.
        await server.replace(build_workflow("b"))
        assert await manifest_order(server) == [BUILTIN_WORKFLOW, "a", "c"]
        assert await plugin_route_status(server, "b") == 404
        # ...and by one that declares again: appended, held once.
        await server.replace(fixture_workflow("b"))
        assert await manifest_order(server) == [BUILTIN_WORKFLOW, "a", "c", "b"]
        assert [spec.workflow for spec in server._specs] == ["a", "c", "b"]


# -- remove -------------------------------------------------------------------


async def test_remove_interrupts_unmounts_and_emits(tmp_path: Path) -> None:
    """22 §Remove: the ids, the 404, the manifest, `unregistered: true`."""

    parked = Parked()
    wf = fixture_workflow("gamedev")
    server = Server(make_settings(tmp_path))
    server.register(wf)
    server.register(parked.workflow("park"))
    async with serving(server):
        run = await server.engine.ops.submit("park", "a run")
        await wait_for(parked.started)
        task = await task_of(server, run.id)

        removed = await server.remove("park")
        assert removed == RemovedWorkflow("park", (task.id,), None)
        (event,) = await named_events(server, EventName.workflow_unregistered)
        assert event.run_id is None
        assert event.data == {"workflow": "park", "task_ids": [task.id]}
        assert (await run_row(server, run.id)).status is RunStatus.running
        async with httpx.AsyncClient(base_url=server.url) as http:
            response = await http.get(f"/api/runs/{run.id}")
        assert response.status_code == 200
        assert response.json()["unregistered"] is True

        assert await plugin_route_status(server, "gamedev") == 200
        gone = await server.remove("gamedev")
        assert gone == RemovedWorkflow("gamedev", (), None)
        assert await plugin_route_status(server, "gamedev") == 404
        assert await manifest_order(server) == [BUILTIN_WORKFLOW]
        assert server.workflows == {}
        assert server.targets == {}


# -- refusals -----------------------------------------------------------------


def _untouched(server: Server, before: tuple[Any, Any, Any]) -> None:
    assert (server.workflows, server.targets, set(server.engine.graphs)) == before


async def test_register_and_register_configured_after_start_raise(
    tmp_path: Path,
) -> None:
    """D226: the call would mount nothing; `add` is named."""

    server = Server(make_settings(tmp_path))
    async with serving(server):
        with pytest.raises(RuntimeError, match="add\\(\\)"):
            server.register(build_workflow("late"))
        with pytest.raises(RuntimeError, match="add\\(\\)"):
            server.register_configured()
        assert server.workflows == {}


async def test_every_stage_the_verbs_raise_leaves_the_server_untouched(
    tmp_path: Path,
) -> None:
    """22 §Wire's `finalize`, `plugins` and `register` stages, as `LoadError`."""

    server = Server(make_settings(tmp_path))
    server.register(build_workflow("taken"), Pool("local", 1), target="t.py:wf")
    async with serving(server):
        before = (server.workflows, server.targets, set(server.engine.graphs))

        unclosed = Workflow("unclosed")

        @unclosed.node(start=True)
        async def start(missing):  # type: ignore[no-untyped-def]
            return missing

        with pytest.raises(LoadError) as raised:
            await server.add(unclosed, target="u.py:wf")
        assert raised.value.stage == "finalize"
        assert raised.value.target == "u.py:wf"
        assert raised.value.detail == str(raised.value)
        _untouched(server, before)

        bad_panel = build_workflow("panelled")
        bad_panel.panel("nope", slot="run", kind="table", node="absent", source="/x")
        with pytest.raises(LoadError) as raised:
            await server.add(bad_panel)
        assert raised.value.stage == "plugins"
        assert raised.value.target == ""
        assert "absent" in raised.value.detail
        _untouched(server, before)

        for wf, says in [
            (build_workflow("ls"), "CLI verb"),
            (build_workflow("local"), "name of a pool"),
        ]:
            with pytest.raises(LoadError) as raised:
                await server.add(wf)
            assert raised.value.stage == "register"
            assert raised.value.conflict is False
            assert says in str(raised.value)
            _untouched(server, before)

        with pytest.raises(LoadError) as raised:
            await server.add(build_workflow("taken"))
        assert raised.value.stage == "register"
        assert raised.value.conflict is True
        _untouched(server, before)

        with pytest.raises(LoadError) as raised:
            await server.replace(build_workflow("unknown"))
        assert raised.value.stage == "register"
        assert raised.value.conflict is False
        assert "not registered" in str(raised.value)
        _untouched(server, before)

        with pytest.raises(LoadError) as raised:
            await server.remove("unknown")
        assert raised.value.stage == "register"
        _untouched(server, before)
        assert await stored_events(server) == []


async def test_targets_are_in_registration_order_with_none_for_objects(
    tmp_path: Path,
) -> None:
    server = Server(make_settings(tmp_path))
    server.register(build_workflow("b"), target="b.py:wf")
    server.register(build_workflow("a"))
    await server.add(build_workflow("c"), target="c.py:wf")
    assert list(server.targets.items()) == [
        ("b", "b.py:wf"),
        ("a", None),
        ("c", "c.py:wf"),
    ]
    assert list(server.workflows) == ["b", "a", "c"]


# -- persistence ---------------------------------------------------------------


async def test_persist_needs_a_target(tmp_path: Path) -> None:
    server = Server(make_settings(tmp_path))
    with pytest.raises(ValueError, match="needs a target"):
        await server.add(build_workflow("obj"), persist=True)
    assert server.workflows == {}
    server.register(build_workflow("held"))
    with pytest.raises(ValueError, match="needs a target"):
        await server.replace(build_workflow("held"), persist=True)
    assert not (tmp_path / "athanore.toml").exists()


async def test_add_with_persist_writes_the_row_and_registers(
    tmp_path: Path,
) -> None:
    """22 §Persistence: one row, the rest of the file byte-identical."""

    toml = tmp_path / "athanore.toml"
    original = (
        "# keep me\nworkers = 2\n\n[pools]\nlocal = 1   # one\n\n"
        '[workflows]\nother = { pool = "local" }   # theirs\n'
    )
    toml.write_text(original)
    target = write_target(tmp_path, "chat", "chat")
    server = Server(make_settings(tmp_path))
    server.register(build_workflow("other"), Pool("local", 1))
    async with serving(server):
        registered = await server.add(
            load_target(target), "local", target=target, persist=True
        )
        assert registered == Registered("chat", toml)
        assert "chat" in server.workflows
        assert server.targets["chat"] == target
        assert toml.read_text() == original + (
            f'chat = {{ target = "{target}", pool = "local" }}\n'
        )
        # Replacing with persist rewrites the row — without the pool the
        # request did not name.
        again = await server.replace(load_target(target), target=target, persist=True)
        assert again == Registered("chat", toml)
        assert toml.read_text() == original + f'chat = {{ target = "{target}" }}\n'
        # Removing with persist takes the row, and only the row.
        removed = await server.remove("chat", persist=True)
        assert removed == RemovedWorkflow("chat", (), toml)
        assert toml.read_text() == original
        # ...and a name with no row is not an error; nothing was touched.
        await server.add(build_workflow("plain"))
        assert await server.remove("plain", persist=True) == RemovedWorkflow(
            "plain", (), None
        )
        assert toml.read_text() == original


async def test_a_failing_validation_writes_nothing(tmp_path: Path) -> None:
    toml = tmp_path / "athanore.toml"
    server = Server(make_settings(tmp_path))
    server.register(build_workflow("taken"))
    async with serving(server):
        with pytest.raises(LoadError):
            await server.add(build_workflow("taken"), target="t.py:wf", persist=True)
        with pytest.raises(KeyError):
            await server.add(
                build_workflow("fresh"), "nope", target="f.py:wf", persist=True
            )
        assert not toml.exists()
        assert "fresh" not in server.workflows


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes read-only files")
async def test_a_failing_write_registers_nothing_and_emits_nothing(
    tmp_path: Path,
) -> None:
    toml = tmp_path / "athanore.toml"
    toml.write_text("[workflows]\n")
    toml.chmod(stat.S_IRUSR)
    server = Server(make_settings(tmp_path))
    try:
        async with serving(server):
            with pytest.raises(PersistError) as raised:
                await server.add(build_workflow("chat"), target="c.py:wf", persist=True)
            assert raised.value.path == toml
            assert server.workflows == {}
            assert "chat" not in server.engine.graphs
            assert await stored_events(server) == []
    finally:
        toml.chmod(stat.S_IRUSR | stat.S_IWUSR)


# -- register_configured ---------------------------------------------------------


def test_register_configured_registers_the_target_rows(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """22 §Persistence for a programmatic host."""

    chat = write_target(tmp_path, "chat", "chat")
    hello = write_target(tmp_path, "hello", "hello")
    mine = write_target(tmp_path, "mine", "mine")
    (tmp_path / "athanore.toml").write_text(
        "[pools]\nplay = 3\n\n[workflows]\n"
        'binding_only = { pool = "play" }\n'
        f'chat = {{ target = "{chat}", pool = "play" }}\n'
        f'hello = {{ target = "{hello}" }}\n'
        f'mine = {{ target = "{mine}" }}\n'
    )
    server = Server(make_settings(tmp_path))
    server.register(build_workflow("mine"), target="typed.py:wf")

    with caplog.at_level(logging.WARNING), structlog.testing.capture_logs() as logs:
        rows = server.register_configured()

    assert rows.registered == ("chat", "hello")
    assert rows.skipped == (Skipped("mine", mine, "typed.py:wf"),)
    assert list(server.workflows) == ["mine", "chat", "hello"]
    assert server.targets == {"mine": "typed.py:wf", "chat": chat, "hello": hello}
    assert server.engine.pools.for_workflow("chat").name == "play"
    assert server.engine.snapshot()["play"]["capacity"] == 3
    assert server.engine.pools.for_workflow("hello").name == "default"
    # One WARNING naming both targets, whichever way structlog is
    # configured when this test runs (a started server routes it through
    # stdlib logging; a fresh process keeps it in structlog).
    said = [str(entry) for entry in logs if entry["log_level"] == "warning"] + [
        str(record.msg)
        for record in caplog.records
        if record.levelno == logging.WARNING
    ]
    assert len(said) == 1
    assert mine in said[0]
    assert "typed.py:wf" in said[0]


def test_register_configured_with_no_rows_or_no_file(tmp_path: Path) -> None:
    server = Server(make_settings(tmp_path))
    assert server.register_configured() == ConfiguredRows((), ())
    (tmp_path / "athanore.toml").write_text('[workflows]\nx = { pool = "p" }\n')
    assert server.register_configured() == ConfiguredRows((), ())
    assert server.workflows == {}


def test_register_configured_refuses_a_key_that_is_not_the_name(
    tmp_path: Path,
) -> None:
    target = write_target(tmp_path, "chat", "chat")
    (tmp_path / "athanore.toml").write_text(
        f'[workflows]\ntypo = {{ target = "{target}" }}\n'
    )
    server = Server(make_settings(tmp_path))
    with pytest.raises(LoadError) as raised:
        server.register_configured()
    assert raised.value.stage == "register"
    assert raised.value.target == target
    assert "typo" in str(raised.value)
    assert "'chat'" in str(raised.value)
    assert server.workflows == {}


def test_register_configured_refuses_an_undeclared_pool(tmp_path: Path) -> None:
    target = write_target(tmp_path, "chat", "chat")
    (tmp_path / "athanore.toml").write_text(
        "[pools]\nlocal = 1\n\n[workflows]\n"
        f'chat = {{ target = "{target}", pool = "sandbox" }}\n'
    )
    server = Server(make_settings(tmp_path))
    with pytest.raises(LayoutError, match="`sandbox`"):
        server.register_configured()
    assert server.workflows == {}


def test_register_configured_reports_a_target_that_will_not_load(
    tmp_path: Path,
) -> None:
    (tmp_path / "athanore.toml").write_text(
        '[workflows]\nchat = { target = "nowhere.py:wf" }\n'
    )
    server = Server(make_settings(tmp_path))
    with pytest.raises(LoadError) as raised:
        server.register_configured()
    assert raised.value.stage == "import"
    assert raised.value.target == "nowhere.py:wf"


async def _run_is(server: Server, run_id: str, status: RunStatus) -> bool:
    return (await run_row(server, run_id)).status is status
