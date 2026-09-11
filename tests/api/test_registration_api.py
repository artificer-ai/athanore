"""`POST`, `PUT` and `DELETE /api/workflows` on a served process (T086, 22 §Wire).

The subject is the wire over the live verbs of T085, so every test here
starts a real `Server` on a real socket and speaks HTTP to it: the
registrar port is what `Server.start` hands `create_app`, and an ASGI
application built by hand would have none (that case — the 503 — is in
`tests/api/test_workflows_api.py`). Every status 22 §Wire lists is
asserted, the `workflow_load_failed` body is checked key for key per
stage, and what the verbs did is read back off `GET /api/workflows`, the
event stream and the `athanore.toml` under `tmp_path`.

Two autouse fixtures are copied from `tests/test_server.py` rather than
imported: `load_target` edits `sys.modules` and `sys.path`, and no verb
may ever write a workflow's `.py`.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import stat
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from pydantic import SecretStr

from athanore.api.registrar import WorkflowRegistrar
from athanore.api.routers.workflows import PERSISTED_HEADER
from athanore.engine import Pool
from athanore.server import Server
from athanore.settings import AthanoreSettings
from athanore.workflow import Workflow

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 10.0

#: The operator token of the auth test.
TOKEN = "operator-token-T086"

#: The keys of the load-failure body, exactly (22 §Wire).
LOAD_FAILED_KEYS = {"error", "code", "target", "stage", "detail"}


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """Undo the `configure_logging` every `Server.start()` performs."""

    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


@pytest.fixture(autouse=True)
def restore_imports() -> Iterator[None]:
    """`load_target` on a file target edits `sys.modules` and `sys.path`."""

    path = list(sys.path)
    modules = set(sys.modules)
    yield
    sys.path[:] = path
    for name in set(sys.modules) - modules:
        del sys.modules[name]


#: The digest of every `.py` the running test wrote through
#: :func:`write_target`, keyed by path — what the file must still hold
#: when the test ends.
_written: dict[Path, str] = {}


@pytest.fixture(autouse=True)
def sources_are_never_written(tmp_path: Path) -> Iterator[None]:
    """22 §Persistence, "Never the source": every `.py` is byte-identical.

    The tests here write and rewrite targets themselves, so the digests
    are taken at each :func:`write_target` rather than before the test:
    what is asserted is that the *server* wrote none of them.
    """

    _written.clear()
    yield
    for path, digest in _written.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path


def write_target(
    tmp_path: Path,
    stem: str,
    name: str,
    node: str = "only",
    *,
    body: str = "    return None\n",
    prelude: str = "",
) -> str:
    """A one-node workflow file under `tmp_path`, and the target naming it."""

    path = tmp_path / f"{stem}.py"
    path.write_text(
        f"{prelude}from athanore.workflow import Workflow\n"
        "\n"
        f'wf = Workflow("{name}")\n'
        "\n"
        "\n"
        "@wf.node(start=True)\n"
        f"async def {node}():\n"
        f"{body}"
    )
    _written[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path}:wf"


def write_parked(tmp_path: Path, stem: str, name: str, node: str = "hold") -> str:
    """A target whose one node parks until it is cancelled."""

    return write_target(
        tmp_path,
        stem,
        name,
        node,
        prelude="import asyncio\n",
        body="    await asyncio.sleep(3600)\n    return None\n",
    )


def build_workflow(name: str = "demo") -> Workflow:
    """A programmatic one-node workflow — a registration with no target."""

    wf = Workflow(name)

    @wf.node(start=True)
    async def only():
        return None

    return wf


def make_settings(tmp_path: Path, **overrides: Any) -> AthanoreSettings:
    fields: dict[str, Any] = {
        "root_path": tmp_path,
        "db_url": f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}",
        "host": "127.0.0.1",
        "port": 0,
        "workers": 2,
    }
    fields.update(overrides)
    return AthanoreSettings(**fields)


@pytest.fixture
def server(tmp_path: Path) -> Server:
    """A server with one programmatic workflow on a `spare` pool, not started."""

    instance = Server(make_settings(tmp_path))
    instance.register(build_workflow("obj"), Pool("spare", 1))
    return instance


@pytest.fixture
async def serving(server: Server) -> AsyncIterator[Server]:
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest.fixture
async def http(serving: Server) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(base_url=serving.url, timeout=DEADLINE) as client:
        yield client


async def wait_until(condition: Callable[[], Awaitable[bool] | bool]) -> None:
    async with asyncio.timeout(DEADLINE):
        while True:
            value = condition()
            if asyncio.iscoroutine(value):
                value = await value
            if value:
                return
            await asyncio.sleep(0.01)


async def submit(http: httpx.AsyncClient, workflow: str) -> str:
    response = await http.post(f"/api/workflows/{workflow}/runs", json={"title": "t"})
    assert response.status_code == 201, response.text
    return str(response.json()["run_id"])


async def in_flight(server: Server, workflow: str) -> list[int]:
    """The task ids of the attempts of `workflow` running right now."""

    await wait_until(lambda: bool(server.engine.attempts_of(workflow)))
    return server.engine.attempts_of(workflow)


async def run_status(http: httpx.AsyncClient, run_id: str) -> str:
    response = await http.get(f"/api/runs/{run_id}")
    assert response.status_code == 200, response.text
    return str(response.json()["status"])


def stable(workflow: dict[str, Any]) -> dict[str, Any]:
    """A `WorkflowOut` without `in_flight`, which is the pool's live count.

    The scheduler reserves a pool's free slots for the length of a claim
    and gives the surplus back, so a read made while the tick a verb
    woke is claiming can see every slot leased; the verbs' responses and
    a later `GET` are the same workflow, not the same instant.
    """

    return {key: value for key, value in workflow.items() if key != "in_flight"}


async def listed(http: httpx.AsyncClient) -> list[str]:
    response = await http.get("/api/workflows")
    assert response.status_code == 200, response.text
    return [entry["name"] for entry in response.json()]


# --------------------------------------------------------------------------
# POST
# --------------------------------------------------------------------------


def test_the_server_is_the_registrar(server: Server) -> None:
    """22 §Wire: `Server` implements the port the API is handed."""

    assert isinstance(server, WorkflowRegistrar)


async def test_post_registers_and_answers_the_workflow(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    """201 with the `GET` view, `target` included; the name is then listed."""

    target = write_target(tmp_path, "hello", "hello")
    response = await http.post("/api/workflows", json={"target": target})
    assert response.status_code == 201, response.text
    assert PERSISTED_HEADER not in response.headers
    body = response.json()
    assert body["name"] == "hello"
    assert body["target"] == target
    assert body["pool"] == "default"
    assert list(body["nodes"]) == ["only"]
    read = await http.get("/api/workflows/hello")
    assert stable(read.json()) == stable(body)
    assert 0 <= body["in_flight"] <= body["capacity"]
    assert await listed(http) == ["hello", "obj"]


async def test_post_of_a_registered_name_is_a_409(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    target = write_target(tmp_path, "hello", "hello")
    assert (
        await http.post("/api/workflows", json={"target": target})
    ).status_code == 201
    again = await http.post("/api/workflows", json={"target": target})
    assert again.status_code == 409
    assert again.json() == {
        "error": "workflow 'hello' is already registered",
        "code": "conflict",
    }
    assert await listed(http) == ["hello", "obj"]


async def test_post_binds_to_the_named_pool(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    target = write_target(tmp_path, "hello", "hello")
    response = await http.post(
        "/api/workflows", json={"target": target, "pool": "spare"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["pool"] == "spare"
    assert response.json()["capacity"] == 1


async def test_an_unknown_pool_is_a_422_naming_the_known(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    """22 §Pools: `{error, code}` only, and the message names the pools."""

    target = write_target(tmp_path, "hello", "hello")
    response = await http.post(
        "/api/workflows", json={"target": target, "pool": "nope"}
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"error", "code"}
    assert body["code"] == "unknown_pool"
    assert "'nope'" in body["error"]
    assert "['spare']" in body["error"]
    assert await listed(http) == ["obj"]


def _broken_targets(tmp_path: Path) -> list[tuple[str, str, str]]:
    """(target, stage, a fragment of `detail`) for every stage 22 §Wire names."""

    cases: list[tuple[str, str, str]] = []
    cases.append(("nocolon", "target", "not a workflow target"))
    cases.append((f"{tmp_path / 'absent.py'}:wf", "import", "is not a file"))
    cases.append(
        (
            write_target(
                tmp_path, "raising", "raising", prelude="raise ValueError('boom')\n"
            ),
            "import",
            "boom",
        )
    )
    cases.append(
        (
            write_target(tmp_path, "noattr", "noattr").replace(":wf", ":missing"),
            "attribute",
            "missing",
        )
    )
    cases.append(
        (
            write_target(tmp_path, "notwf", "notwf", prelude="number = 3\n").replace(
                ":wf", ":number"
            ),
            "attribute",
            "not a Workflow",
        )
    )
    unclosed = tmp_path / "unclosed.py"
    unclosed.write_text(
        "from athanore.workflow import Workflow\n"
        'wf = Workflow("unclosed")\n'
        "@wf.node(start=True)\n"
        "async def start(missing):\n"
        "    return missing\n"
    )
    cases.append((f"{unclosed}:wf", "finalize", "missing"))
    panelled = tmp_path / "panelled.py"
    panelled.write_text(
        "from athanore.workflow import Workflow\n"
        'wf = Workflow("panelled")\n'
        "@wf.node(start=True)\n"
        "async def only():\n"
        "    return None\n"
        'wf.panel("nope", slot="run", kind="table", node="absent", source="/x")\n'
    )
    cases.append((f"{panelled}:wf", "plugins", "absent"))
    cases.append((write_target(tmp_path, "verb", "ls"), "register", "CLI verb"))
    return cases


async def test_the_load_failure_body_names_the_stage(
    tmp_path: Path, http: httpx.AsyncClient, caplog: pytest.LogCaptureFixture
) -> None:
    """22 §Wire's body, key for key, for each of the six stages."""

    for target, stage, fragment in _broken_targets(tmp_path):
        response = await http.post("/api/workflows", json={"target": target})
        assert response.status_code == 422, (target, response.text)
        body = response.json()
        assert set(body) == LOAD_FAILED_KEYS, target
        assert body["code"] == "workflow_load_failed"
        assert body["stage"] == stage, target
        assert body["target"] == target
        assert fragment in body["detail"], (target, body)
        assert body["error"]
        # The traceback is in the log, not on the wire.
        assert "Traceback" not in response.text
    assert await listed(http) == ["obj"]
    failures = [
        record
        for record in caplog.records
        if "workflow registration failed" in record.getMessage()
    ]
    assert len(failures) == 8


# --------------------------------------------------------------------------
# PUT
# --------------------------------------------------------------------------


async def test_put_reloads_the_edited_file(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    """200, the node set changed, `/source` shows the new text."""

    target = write_target(tmp_path, "hello", "hello", "first")
    assert (
        await http.post("/api/workflows", json={"target": target})
    ).status_code == 201
    write_target(tmp_path, "hello", "hello", "second")
    response = await http.put("/api/workflows/hello", json={"target": target})
    assert response.status_code == 200, response.text
    assert list(response.json()["nodes"]) == ["second"]
    assert response.json()["target"] == target
    read = await http.get("/api/workflows/hello")
    assert stable(response.json()) == stable(read.json())
    source = await http.get("/api/workflows/hello/source")
    assert "async def second" in source.json()["source"]
    assert list(source.json()["nodes"]) == ["second"]


async def test_put_without_a_target_re_resolves_the_recorded_one(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    target = write_target(tmp_path, "hello", "hello", "first")
    assert (
        await http.post("/api/workflows", json={"target": target})
    ).status_code == 201
    write_target(tmp_path, "hello", "hello", "second")
    response = await http.put("/api/workflows/hello", json={})
    assert response.status_code == 200, response.text
    assert list(response.json()["nodes"]) == ["second"]


async def test_put_without_a_target_on_a_programmatic_workflow_is_stage_target(
    http: httpx.AsyncClient,
) -> None:
    response = await http.put("/api/workflows/obj", json={})
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == LOAD_FAILED_KEYS
    assert body["code"] == "workflow_load_failed"
    assert body["stage"] == "target"
    assert body["target"] == ""
    assert "no recorded target" in body["error"]


async def test_put_whose_target_names_another_workflow_is_a_409(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    """22 §Reloading a module: a new name is a new workflow — `POST` it."""

    hello = write_target(tmp_path, "hello", "hello")
    other = write_target(tmp_path, "other", "other", "theirs")
    for target in (hello, other):
        assert (
            await http.post("/api/workflows", json={"target": target})
        ).status_code == 201
    # `hello.py` now defines `other`, a name that *is* registered — the
    # check must fire before `replace` could swap the wrong one.
    write_target(tmp_path, "hello", "other", "swapped")
    response = await http.put("/api/workflows/hello", json={})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "conflict"
    assert "names workflow 'other'" in response.json()["error"]
    assert list((await http.get("/api/workflows/other")).json()["nodes"]) == ["theirs"]
    assert list((await http.get("/api/workflows/hello")).json()["nodes"]) == ["only"]
    # ...and a name that is not registered at all is refused the same way.
    write_target(tmp_path, "hello", "fresh")
    response = await http.put("/api/workflows/hello", json={})
    assert response.status_code == 409
    assert await listed(http) == ["hello", "obj", "other"]


async def test_put_refuses_a_pool_move_with_attempts_in_flight(
    tmp_path: Path, serving: Server, http: httpx.AsyncClient
) -> None:
    """22 §Pools: 409 while an attempt is mid-node, 200 once it is gone."""

    target = write_parked(tmp_path, "parked", "parked")
    assert (
        await http.post("/api/workflows", json={"target": target})
    ).status_code == 201
    run_id = await submit(http, "parked")
    await in_flight(serving, "parked")
    refused = await http.put("/api/workflows/parked", json={"pool": "spare"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "conflict"
    assert "in flight" in refused.json()["error"]
    assert (await http.get("/api/workflows/parked")).json()["pool"] == "default"

    cancelled = await http.post(f"/api/runs/{run_id}/cancel")
    assert cancelled.status_code in (200, 204), cancelled.text
    await wait_until(lambda: not serving.engine.attempts_of("parked"))
    moved = await http.put("/api/workflows/parked", json={"pool": "spare"})
    assert moved.status_code == 200, moved.text
    assert moved.json()["pool"] == "spare"


async def test_put_of_an_unknown_workflow_is_a_404(http: httpx.AsyncClient) -> None:
    response = await http.put("/api/workflows/nope", json={"target": "x.py:wf"})
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_workflow"


# --------------------------------------------------------------------------
# DELETE
# --------------------------------------------------------------------------


async def test_delete_interrupts_and_the_run_reads_unregistered(
    tmp_path: Path, serving: Server, http: httpx.AsyncClient
) -> None:
    """22 §Remove, then §Add step 3: interrupted, flagged, resumed."""

    target = write_parked(tmp_path, "parked", "parked")
    assert (
        await http.post("/api/workflows", json={"target": target})
    ).status_code == 201
    run_id = await submit(http, "parked")
    task_ids = await in_flight(serving, "parked")

    response = await http.delete("/api/workflows/parked")
    assert response.status_code == 200, response.text
    assert response.json() == {"workflow": "parked", "task_ids": task_ids}
    assert PERSISTED_HEADER not in response.headers
    assert await listed(http) == ["obj"]
    run = (await http.get(f"/api/runs/{run_id}")).json()
    assert run["status"] == "running"
    assert run["unregistered"] is True

    # Edited not to park, then added back: the row is recovered and runs.
    write_target(tmp_path, "parked", "parked", "hold")
    back = await http.post("/api/workflows", json={"target": target})
    assert back.status_code == 201, back.text
    await wait_until(lambda: _is(run_status(http, run_id), "completed"))
    run = (await http.get(f"/api/runs/{run_id}")).json()
    assert run["unregistered"] is False


async def _is(status: Awaitable[str], expected: str) -> bool:
    return await status == expected


async def test_delete_of_a_quiet_workflow_reports_no_tasks(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    target = write_target(tmp_path, "hello", "hello")
    assert (
        await http.post("/api/workflows", json={"target": target})
    ).status_code == 201
    response = await http.delete("/api/workflows/hello")
    assert response.status_code == 200
    assert response.json() == {"workflow": "hello", "task_ids": []}


async def test_delete_of_an_unknown_workflow_is_a_404(http: httpx.AsyncClient) -> None:
    response = await http.delete("/api/workflows/nope")
    assert response.status_code == 404
    assert response.json()["code"] == "unknown_workflow"


# --------------------------------------------------------------------------
# persist
# --------------------------------------------------------------------------

#: A fixture `athanore.toml` with a comment and a row the verbs never touch.
ORIGINAL = (
    "# keep me\nworkers = 2\n\n[pools]\nspare = 1   # one\n\n"
    '[workflows]\nobj = { pool = "spare" }   # theirs\n'
)


async def test_persist_writes_exactly_one_row_and_reports_the_path(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    """22 §Persistence, on each verb: one row changes, the rest is byte-identical."""

    toml = tmp_path / "athanore.toml"
    toml.write_text(ORIGINAL)
    target = write_target(tmp_path, "hello", "hello")

    added = await http.post(
        "/api/workflows", json={"target": target, "pool": "spare", "persist": True}
    )
    assert added.status_code == 201, added.text
    assert added.headers[PERSISTED_HEADER] == str(toml)
    assert toml.read_text() == ORIGINAL + (
        f'hello = {{ target = "{target}", pool = "spare" }}\n'
    )

    # A reload that names no pool rewrites the row without one.
    reloaded = await http.put("/api/workflows/hello", json={"persist": True})
    assert reloaded.status_code == 200, reloaded.text
    assert reloaded.headers[PERSISTED_HEADER] == str(toml)
    assert toml.read_text() == ORIGINAL + f'hello = {{ target = "{target}" }}\n'

    # Without `persist`, nothing on disk changes and no receipt is sent.
    quiet = await http.put("/api/workflows/hello", json={})
    assert quiet.status_code == 200
    assert PERSISTED_HEADER not in quiet.headers
    assert toml.read_text() == ORIGINAL + f'hello = {{ target = "{target}" }}\n'

    removed = await http.delete("/api/workflows/hello", params={"persist": "true"})
    assert removed.status_code == 200, removed.text
    assert removed.headers[PERSISTED_HEADER] == str(toml)
    assert toml.read_text() == ORIGINAL

    # A name with no row: not an error, nothing touched, no receipt (D244).
    plain = await http.post("/api/workflows", json={"target": target})
    assert plain.status_code == 201
    gone = await http.delete("/api/workflows/hello", params={"persist": "true"})
    assert gone.status_code == 200
    assert PERSISTED_HEADER not in gone.headers
    assert toml.read_text() == ORIGINAL


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes read-only files")
async def test_a_write_that_fails_is_a_500_and_registers_nothing(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    """22 §Persistence: `persist_failed {path, detail}`, server as it was."""

    toml = tmp_path / "athanore.toml"
    toml.write_text(ORIGINAL)
    toml.chmod(stat.S_IRUSR)
    target = write_target(tmp_path, "hello", "hello", "first")
    try:
        response = await http.post(
            "/api/workflows", json={"target": target, "persist": True}
        )
        assert response.status_code == 500, response.text
        body = response.json()
        assert set(body) == {"error", "code", "path", "detail"}
        assert body["code"] == "persist_failed"
        assert body["path"] == str(toml)
        assert body["detail"]
        assert "registration was not changed" in body["error"]
        assert await listed(http) == ["obj"]

        # For a PUT, the old graph stays.
        assert (
            await http.post("/api/workflows", json={"target": target})
        ).status_code == 201
        write_target(tmp_path, "hello", "hello", "second")
        response = await http.put("/api/workflows/hello", json={"persist": True})
        assert response.status_code == 500
        assert response.json()["code"] == "persist_failed"
        assert list((await http.get("/api/workflows/hello")).json()["nodes"]) == [
            "first"
        ]
    finally:
        toml.chmod(stat.S_IRUSR | stat.S_IWUSR)


# --------------------------------------------------------------------------
# Events, and the door
# --------------------------------------------------------------------------


async def test_the_three_events_reach_the_stream_with_no_run_id(
    tmp_path: Path, http: httpx.AsyncClient
) -> None:
    """22 §Events on `GET /api/events?names=workflow.*`, in order."""

    target = write_target(tmp_path, "hello", "hello")
    assert (
        await http.post("/api/workflows", json={"target": target})
    ).status_code == 201
    assert (await http.put("/api/workflows/hello", json={})).status_code == 200
    assert (await http.delete("/api/workflows/hello")).status_code == 200

    frames: list[dict[str, Any]] = []
    async with http.stream(
        "GET", "/api/events", params={"after": 0, "names": "workflow.*"}
    ) as stream:
        assert stream.status_code == 200
        name: str | None = None
        async with asyncio.timeout(DEADLINE):
            async for raw in stream.aiter_lines():
                if raw.startswith("event:"):
                    name = raw.partition(":")[2].strip()
                elif raw.startswith("data:") and name is not None:
                    frames.append({"name": name, **json.loads(raw.partition(":")[2])})
                    name = None
                if len(frames) == 3:
                    break

    assert [frame["name"] for frame in frames] == [
        "workflow.registered",
        "workflow.replaced",
        "workflow.unregistered",
    ]
    for frame in frames:
        assert frame.get("run_id") is None
        assert frame["data"]["workflow"] == "hello"
    assert frames[0]["data"]["target"] == target
    assert frames[2]["data"]["task_ids"] == []


async def test_the_routes_are_behind_the_operator_door(
    tmp_path: Path,
) -> None:
    """12 §Plugins: operator routes; a task token opens nothing here."""

    settings = make_settings(
        tmp_path, require_token=True, operator_token=SecretStr(TOKEN)
    )
    server = Server(settings)
    server.register(build_workflow("obj"))
    target = write_target(tmp_path, "hello", "hello")
    await server.start()
    try:
        async with httpx.AsyncClient(base_url=server.url, timeout=DEADLINE) as http:
            task_token = {"X-Athanore-Token": "any-task-token"}
            for method, path, body in (
                ("POST", "/api/workflows", {"target": target}),
                ("PUT", "/api/workflows/obj", {}),
                ("DELETE", "/api/workflows/obj", None),
            ):
                refused = await http.request(
                    method, path, json=body, headers=task_token
                )
                assert refused.status_code == 401, (method, refused.text)
                assert refused.json()["code"] == "unauthorized"
            bearer = {"Authorization": f"Bearer {TOKEN}"}
            allowed = await http.post(
                "/api/workflows", json={"target": target}, headers=bearer
            )
            assert allowed.status_code == 201, allowed.text
            removed = await http.delete("/api/workflows/hello", headers=bearer)
            assert removed.status_code == 200, removed.text
    finally:
        await server.stop()
