"""The auth matrix of 13 §Pyramid, and the two open system routes (T043).

Every row of the matrix is here: a plain loopback bind needs nothing, a
network bind without a token is a server that will not start, a network
bind with one answers 401 or 200 on the header, `require_token` turns the
same rule on for loopback, and a task token works for exactly one task
for exactly as long as that attempt is live.

What has to hold here is that the two dependencies decide correctly, so
the subject is the door rather than the room behind it. `task_auth` is
exercised against the real agent route (T045); `operator_auth` against a
plainly guarded route this module hangs off a real `create_app()`, and
against the real `/api/events` (T046) for the query-parameter exception.

Only the *refusals* on `/api/events` are asserted here. A stream that
opens does not end, and `httpx.ASGITransport` runs an application to
completion before it hands back a response, so the accepting half of
that route's matrix is in `test_sse.py`, where the harness that can read
a live stream lives.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
import structlog
from fastapi import Depends, FastAPI

from athanore.api import VERSION
from athanore.api.app import create_app
from athanore.api.deps import MissingOperatorToken, auth_mode
from athanore.api.deps import operator_auth as operator_auth_dep
from athanore.engine import Engine
from athanore.engine.pools import Pool
from athanore.events.bus import EventBus
from athanore.logging import REDACTED, configure_logging
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.repos.tasks import ClaimedTask
from athanore.store.rows import TaskStatus
from athanore.store.tables import metadata
from athanore.store.uow import Store

#: The operator token under test. Distinctive enough that the redaction
#: assertions can look for it in a whole stream of log output.
TOKEN = "operator-token-1WCXeYcxG4G8"

#: A workflow name for the runs this module submits. Nothing is
#: registered on an engine here — the store is what mints a task token,
#: and it does not care whether the workflow exists.
WORKFLOW = "wf"


# -- fixtures and helpers ---------------------------------------------------


def make_settings(root: Path, **overrides: Any) -> AthanoreSettings:
    """Settings pinned to ``root``, with every auth field passed explicitly.

    ``root_path`` matters more than it looks: `effective_operator_token`
    falls back to ``{root}/.athanore/token``, so a test that did not pin
    it would read the developer's own token file.
    """

    return AthanoreSettings(
        root_path=root,
        db_url=f"sqlite+aiosqlite:///{root / 'athanore.db'}",
        **overrides,
    )


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    """An empty SQLite store, on a file, for one test."""

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, EventBus())
    finally:
        await engine.dispose()


def build_app(
    settings: AthanoreSettings,
    store: Store | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    """A real application, plus one plainly guarded route to knock on.

    Every real operator route needs a store, a run or a workflow to
    answer at all, and none of that is the subject here: what is being
    asserted is which callers get past the dependency.
    """

    app = create_app(settings=settings, engine=engine, store=store)

    @app.get("/api/guarded", dependencies=[Depends(operator_auth_dep)])
    async def guarded() -> dict[str, bool]:
        return {"ok": True}

    return app


def client(app: FastAPI) -> httpx.AsyncClient:
    """An HTTP client speaking ASGI to ``app``."""

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    )


async def claim_one(store: Store) -> ClaimedTask:
    """A submitted run with one claimed attempt, and that attempt's token."""

    async with store.uow() as uow:
        run = await uow.runs.insert(WORKFLOW, "a run")
        await uow.tasks.enqueue(run.id, "start", None, 0, False)
    async with store.uow() as uow:
        claimed = await uow.tasks.claim_ready(1, [WORKFLOW])
    assert claimed, "the claim minted no token"
    return claimed[0]


# -- auth_mode --------------------------------------------------------------


@pytest.mark.parametrize(
    ("host", "require_token", "expected"),
    [
        ("127.0.0.1", False, "off"),
        ("localhost", False, "off"),
        ("::1", False, "off"),
        ("127.0.0.1", True, "token"),
        ("0.0.0.0", False, "token"),
        ("192.168.1.10", False, "token"),
    ],
)
def test_auth_mode_is_off_only_on_a_plain_loopback_bind(
    tmp_path: Path, host: str, require_token: bool, expected: str
) -> None:
    """The rule of 12 §Operator token, and D47's `require_token` half."""

    settings = make_settings(
        tmp_path, host=host, require_token=require_token, operator_token=TOKEN
    )
    assert auth_mode(settings) == expected


# -- the server refuses to start without a token it would need --------------


def test_a_network_bind_without_a_token_refuses_to_start(tmp_path: Path) -> None:
    """S1 of 12: binding a network without a token is a startup failure."""

    settings = make_settings(tmp_path, host="0.0.0.0")
    with pytest.raises(MissingOperatorToken) as raised:
        create_app(settings=settings)
    assert "is not loopback" in str(raised.value)
    assert "token rotate" in str(raised.value)


def test_require_token_without_a_token_refuses_to_start(tmp_path: Path) -> None:
    """Auth that could never succeed is refused, loopback or not (D47)."""

    settings = make_settings(tmp_path, require_token=True)
    with pytest.raises(MissingOperatorToken):
        create_app(settings=settings)


def test_the_token_file_is_enough_to_start_a_network_bind(tmp_path: Path) -> None:
    """`athanore token rotate` writes a file; nothing has to be exported."""

    (tmp_path / ".athanore").mkdir()
    (tmp_path / ".athanore" / "token").write_text(f"{TOKEN}\n")
    settings = make_settings(tmp_path, host="0.0.0.0")

    assert isinstance(create_app(settings=settings), FastAPI)


# -- the operator matrix ----------------------------------------------------


async def test_a_loopback_bind_needs_no_credential(tmp_path: Path) -> None:
    """The default deployment sees no login at all (12 §Posture)."""

    app = build_app(make_settings(tmp_path))
    async with client(app) as http:
        assert (await http.get("/api/guarded")).status_code == 200


async def test_a_network_bind_401s_without_the_header(tmp_path: Path) -> None:
    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        response = await http.get("/api/guarded")

    assert response.status_code == 401
    assert response.json() == {
        "error": "operator token required",
        "code": "unauthorized",
    }


async def test_a_network_bind_accepts_the_operator_token(tmp_path: Path) -> None:
    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        response = await http.get(
            "/api/guarded", headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert response.status_code == 200


@pytest.mark.parametrize(
    "header",
    [
        f"Bearer {TOKEN}x",
        f"Bearer {TOKEN[:-1]}",
        f"Token {TOKEN}",
        TOKEN,
        "Bearer ",
    ],
    ids=["longer", "shorter", "wrong-scheme", "no-scheme", "empty"],
)
async def test_anything_but_the_exact_bearer_token_is_401(
    tmp_path: Path, header: str
) -> None:
    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        response = await http.get("/api/guarded", headers={"Authorization": header})

    assert response.status_code == 401


async def test_a_non_ascii_credential_is_401_and_not_a_500(tmp_path: Path) -> None:
    """`hmac.compare_digest` raises on a non-ASCII `str`; the bytes do not.

    A header cannot carry one — httpx and every other client refuse to
    encode it — but a query parameter is percent-decoded straight into a
    `str`, so the one route that reads a credential from the URL is the
    one place this can arrive.
    """

    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        response = await http.get("/api/events", params={"access_token": "ünïcode"})

    assert response.status_code == 401


async def test_require_token_turns_auth_on_for_a_loopback_bind(
    tmp_path: Path,
) -> None:
    """The reverse-proxy case: loopback, and still 401 without the header (D47)."""

    settings = make_settings(tmp_path, require_token=True, operator_token=TOKEN)
    app = build_app(settings)
    async with client(app) as http:
        assert (await http.get("/api/guarded")).status_code == 401
        authorised = await http.get(
            "/api/guarded", headers={"Authorization": f"Bearer {TOKEN}"}
        )

    assert authorised.status_code == 200


# -- the SSE query-parameter exception --------------------------------------


async def test_the_events_route_still_refuses_a_wrong_token_in_the_query(
    tmp_path: Path,
) -> None:
    """`EventSource` cannot set a header, so this one route takes a query.

    The credential is checked as it would be in a header: a wrong one is
    refused. That the right one is *accepted* is asserted in `test_sse.py`
    against the stream it opens.
    """

    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        assert (await http.get("/api/events?access_token=wrong")).status_code == 401


async def test_no_other_route_accepts_the_token_in_the_query(tmp_path: Path) -> None:
    """The exception is scoped to `GET /api/events` and nothing else."""

    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        response = await http.get(f"/api/guarded?access_token={TOKEN}")

    assert response.status_code == 401


# -- the two open routes ----------------------------------------------------


async def test_health_and_me_stay_open_on_a_token_bind(tmp_path: Path) -> None:
    """Asking whether a credential is needed cannot itself need one (08)."""

    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        assert (await http.get("/api/health")).status_code == 200
        assert (await http.get("/api/me")).status_code == 200


async def test_me_reports_the_mode_and_whether_this_request_satisfies_it(
    tmp_path: Path,
) -> None:
    app = build_app(make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN))
    async with client(app) as http:
        anonymous = (await http.get("/api/me")).json()
        authorised = (
            await http.get("/api/me", headers={"Authorization": f"Bearer {TOKEN}"})
        ).json()

    assert anonymous["auth"] == "token"
    assert anonymous["authenticated"] is False
    assert authorised["authenticated"] is True
    assert authorised["version"] == VERSION
    assert authorised["features"] == []
    assert datetime.fromisoformat(authorised["started_at"]) == app.state.started_at


async def test_me_reports_full_rights_when_auth_is_off(tmp_path: Path) -> None:
    """There is nothing to prove on loopback, so the SPA shows no token screen."""

    app = build_app(make_settings(tmp_path))
    async with client(app) as http:
        body = (await http.get("/api/me")).json()

    assert body["auth"] == "off"
    assert body["authenticated"] is True


async def test_health_reports_the_counts_and_the_pools(
    tmp_path: Path, store: Store
) -> None:
    settings = make_settings(tmp_path)
    engine = Engine(settings, store, EventBus())
    engine.pools.add(Pool("sandbox", capacity=2))
    engine.pools.get("sandbox").try_acquire()
    claimed = await claim_one(store)

    app = build_app(settings, store=store, engine=engine)
    async with client(app) as http:
        body = (await http.get("/api/health")).json()

    assert body["ok"] is True
    assert body["version"] == VERSION
    assert body["runs_running"] == 1
    assert body["tasks_in_progress"] == 1
    assert body["pools"] == {"sandbox": {"capacity": 2, "in_flight": 1}}
    # No ids, no titles: health says how much, never what (12).
    assert claimed.task.run_id not in json.dumps(body)


async def test_health_counts_a_waiting_task_as_not_in_progress(
    tmp_path: Path, store: Store
) -> None:
    """The drain of 04 §Shutdown ends while a question is still open."""

    claimed = await claim_one(store)
    async with store.uow() as uow:
        await uow.tasks.set_status(claimed.task.id, TaskStatus.waiting.value)

    app = build_app(make_settings(tmp_path), store=store)
    async with client(app) as http:
        body = (await http.get("/api/health")).json()

    assert body["tasks_in_progress"] == 0


async def test_health_omits_the_counts_it_cannot_measure(tmp_path: Path) -> None:
    """Unknown is omitted, never zero-filled (02 §Real data only)."""

    app = build_app(make_settings(tmp_path))
    async with client(app) as http:
        body = (await http.get("/api/health")).json()

    assert body == {"ok": True, "version": VERSION}


# -- task tokens ------------------------------------------------------------


async def test_a_task_token_reaches_its_own_task(tmp_path: Path, store: Store) -> None:
    claimed = await claim_one(store)
    app = build_app(make_settings(tmp_path), store=store)

    async with client(app) as http:
        response = await http.get(
            f"/api/agent/tasks/{claimed.task.id}",
            headers={"X-Athanore-Token": claimed.token},
        )

    assert response.status_code == 200
    assert response.json()["task_id"] == claimed.task.id


async def test_a_task_token_does_not_reach_another_task(
    tmp_path: Path, store: Store
) -> None:
    """One task's rights, and only that one (12 §Posture, goal 2)."""

    mine = await claim_one(store)
    theirs = await claim_one(store)
    app = build_app(make_settings(tmp_path), store=store)

    async with client(app) as http:
        response = await http.get(
            f"/api/agent/tasks/{theirs.task.id}",
            headers={"X-Athanore-Token": mine.token},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_an_unknown_task_token_is_403(tmp_path: Path, store: Store) -> None:
    claimed = await claim_one(store)
    app = build_app(make_settings(tmp_path), store=store)

    async with client(app) as http:
        response = await http.get(
            f"/api/agent/tasks/{claimed.task.id}",
            headers={"X-Athanore-Token": "not-a-token"},
        )

    assert response.status_code == 403


async def test_a_task_token_is_dead_once_the_attempt_finishes(
    tmp_path: Path, store: Store
) -> None:
    """Valid only while `in_progress` or `waiting`; 403 after that (12)."""

    claimed = await claim_one(store)
    app = build_app(make_settings(tmp_path), store=store)
    headers = {"X-Athanore-Token": claimed.token}

    async with client(app) as http:
        live = await http.get(f"/api/agent/tasks/{claimed.task.id}", headers=headers)
        async with store.uow() as uow:
            await uow.tasks.finish(claimed.task.id, TaskStatus.done.value, result=1)
        expired = await http.get(f"/api/agent/tasks/{claimed.task.id}", headers=headers)

    assert live.status_code == 200
    assert expired.status_code == 403


async def test_a_waiting_attempt_keeps_its_token(tmp_path: Path, store: Store) -> None:
    """A body parked on a human is still the agent's to write to (04 §Waiting)."""

    claimed = await claim_one(store)
    async with store.uow() as uow:
        await uow.tasks.set_status(claimed.task.id, TaskStatus.waiting.value)

    app = build_app(make_settings(tmp_path), store=store)
    async with client(app) as http:
        response = await http.get(
            f"/api/agent/tasks/{claimed.task.id}",
            headers={"X-Athanore-Token": claimed.token},
        )

    assert response.status_code == 200


async def test_a_task_token_is_not_read_from_the_query(
    tmp_path: Path, store: Store
) -> None:
    """Header only — S3 of 12 §Review of the MVP."""

    claimed = await claim_one(store)
    app = build_app(make_settings(tmp_path), store=store)

    async with client(app) as http:
        response = await http.get(
            f"/api/agent/tasks/{claimed.task.id}?token={claimed.token}"
        )

    assert response.status_code == 422
    assert response.json()["code"] == "validation"
    assert response.json()["errors"][0]["loc"] == ["header", "x-athanore-token"]


async def test_an_operator_token_does_not_open_an_agent_route(
    tmp_path: Path, store: Store
) -> None:
    """The two credentials are not interchangeable in either direction."""

    claimed = await claim_one(store)
    settings = make_settings(tmp_path, host="0.0.0.0", operator_token=TOKEN)
    app = build_app(settings, store=store)

    async with client(app) as http:
        as_operator = await http.get(
            f"/api/agent/tasks/{claimed.task.id}",
            headers={"X-Athanore-Token": TOKEN},
        )
        as_agent = await http.get(
            "/api/guarded", headers={"Authorization": f"Bearer {claimed.token}"}
        )

    assert as_operator.status_code == 403
    assert as_agent.status_code == 401


# -- redaction --------------------------------------------------------------


@pytest.fixture
def reset_logging() -> Iterator[None]:
    """Undo `configure_logging` after a test that called it.

    The tests configure logging themselves rather than taking it from
    fixture setup: a `StreamHandler` binds to whatever `sys.stderr` is
    when it is built, and pytest swaps that stream between the setup and
    call phases — a handler built in setup writes to a closed file by the
    time the test logs anything.
    """

    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


@pytest.mark.usefixtures("reset_logging")
def test_the_sse_query_string_is_redacted_in_the_access_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """uvicorn's access line carries the full path, query string and all."""

    configure_logging("json")
    logging.getLogger("uvicorn.access").info(
        '%s - "%s %s HTTP/%s" %d',
        "10.0.0.4:53122",
        "GET",
        f"/api/events?after=7&access_token={TOKEN}",
        "1.1",
        200,
    )

    output = capsys.readouterr().err
    assert TOKEN not in output
    assert f"access_token={REDACTED}" in output
    # The rest of the line survives: redaction must not cost the log its
    # usefulness.
    assert "after=7" in output


@pytest.mark.usefixtures("reset_logging")
def test_an_authorization_header_is_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The credential is an argument, so the format string cannot be rewritten."""

    configure_logging("json")
    logging.getLogger("athanore.test").warning(
        "refused %s with Authorization: Bearer %s", "GET /api/runs", TOKEN
    )

    output = capsys.readouterr().err
    assert TOKEN not in output
    assert REDACTED in output
    assert "GET /api/runs" in output


@pytest.mark.usefixtures("reset_logging")
def test_a_credential_passed_as_a_structlog_keyword_is_redacted(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The bare value has nothing around it to match, so the *key* decides."""

    configure_logging("json")
    structlog.get_logger("athanore.test").warning(
        "unauthorized",
        authorization=f"Bearer {TOKEN}",
        access_token=TOKEN,
        headers={"X-Athanore-Token": TOKEN},
        path=f"/api/events?access_token={TOKEN}",
    )

    output = capsys.readouterr().err
    assert TOKEN not in output
    record = json.loads(output)
    assert record["authorization"] == REDACTED
    assert record["access_token"] == REDACTED
    assert record["headers"] == {"X-Athanore-Token": REDACTED}
    assert record["path"] == f"/api/events?access_token={REDACTED}"


@pytest.mark.usefixtures("reset_logging")
def test_redaction_never_drops_or_mangles_an_innocent_record(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A log line with nothing to hide comes through as it was written."""

    configure_logging("json")
    logging.getLogger("athanore.test").info("claimed %d task(s) for %s", 3, "sandbox")

    assert "claimed 3 task(s) for sandbox" in capsys.readouterr().err
