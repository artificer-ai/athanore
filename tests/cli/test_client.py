"""The CLI's spine: where the server is, how it is asked, what `$?` says.

The client is tested against a **real HTTP server** rather than a mocked
transport. It is thirty lines of `http.server` (below), and what it buys
is that the thing under test is the client as it ships: its own
transport, its own headers on the wire, and a real `text/event-stream`
read frame by frame off a socket. A mocked transport would test the code
around httpx and not the configuration of httpx, which is where a client
this small keeps most of its behaviour.

The exit codes are driven by the failure each one names (11 §Exit
codes), through :func:`athanore.cli.output.dispatch` itself: a stub typer
app whose command raises what a verb would raise is how 1 and 3 are
produced, because T052 has no verbs yet and inventing one to test the
wrapper would test the verb instead. 0 and 2 come from the real
application, which already answers `--help` and refuses an unknown verb.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import typer
from rich.console import Console

from athanore.cli import Options, main
from athanore.cli import athanore as global_options
from athanore.cli.client import (
    DEFAULT_URL,
    RETRIES,
    ApiClientError,
    Client,
    ServerEvent,
    config_path,
    read_config,
    resolve,
)
from athanore.cli.output import (
    EXIT_API_ERROR,
    EXIT_OK,
    EXIT_UNREACHABLE,
    EXIT_USAGE,
    Column,
    dispatch,
    emit,
)

# --------------------------------------------------------------------------
# A server to talk to
# --------------------------------------------------------------------------


@dataclass
class Reply:
    """What the stub answers on one path."""

    status: int = 200
    body: Any = None
    text: str | None = None
    content_type: str = "application/json"
    #: SSE chunks, written in order and then the connection closed. Each
    #: is raw stream text, so a test writes the framing it means to test.
    sse: Sequence[str] | None = None


@dataclass
class Received:
    """One request the stub was sent."""

    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes = b""


@dataclass
class Stub:
    """A live HTTP server on a free loopback port."""

    routes: dict[str, Reply] = field(default_factory=dict)
    requests: list[Received] = field(default_factory=list)
    server: ThreadingHTTPServer | None = None

    @property
    def url(self) -> str:
        assert self.server is not None
        host, port = self.server.server_address[:2]
        return f"http://{host}:{port}"

    def route(self, path: str, reply: Reply) -> None:
        self.routes[path] = reply

    @property
    def last(self) -> Received:
        assert self.requests, "the client sent nothing"
        return self.requests[-1]


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    @property
    def stub(self) -> Stub:
        return self.server.stub  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        return  # a request per line on stderr would drown the suite

    def do_GET(self) -> None:
        self._answer("GET")

    def do_POST(self) -> None:
        self._answer("POST")

    def do_PATCH(self) -> None:
        self._answer("PATCH")

    def do_DELETE(self) -> None:
        self._answer("DELETE")

    def _answer(self, method: str) -> None:
        parsed = urlsplit(self.path)
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        self.stub.requests.append(
            Received(
                method=method,
                path=parsed.path,
                query=parse_qs(parsed.query),
                headers={k.lower(): v for k, v in self.headers.items()},
                body=body,
            )
        )
        reply = self.stub.routes.get(parsed.path)
        if reply is None:
            reply = Reply(404, {"error": "not found", "code": "not_found"})
        if reply.sse is not None:
            self._answer_sse(reply)
            return
        if reply.text is not None:
            payload = reply.text.encode()
        elif reply.body is None:
            payload = b""
        else:
            payload = json.dumps(reply.body).encode()
        self.send_response(reply.status)
        if payload:
            self.send_header("content-type", reply.content_type)
        self.send_header("content-length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def _answer_sse(self, reply: Reply) -> None:
        assert reply.sse is not None
        self.send_response(reply.status)
        self.send_header("content-type", "text/event-stream")
        self.send_header("connection", "close")
        self.end_headers()
        self.close_connection = True
        for chunk in reply.sse:
            self.wfile.write(chunk.encode())
            self.wfile.flush()


@pytest.fixture(autouse=True)
def no_ambient_connection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing this machine happens to be configured with reaches a test.

    `Client()` resolves from the environment and `~/.config` by design,
    so a developer with `ATHANORE_TOKEN` exported would otherwise see a
    different suite than CI does.
    """

    monkeypatch.delenv("ATHANORE_URL", raising=False)
    monkeypatch.delenv("ATHANORE_TOKEN", raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))


@pytest.fixture
def stub() -> Iterator[Stub]:
    """A stub API on 127.0.0.1, torn down with the test."""

    holder = Stub()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    server.daemon_threads = True
    server.stub = holder  # type: ignore[attr-defined]
    holder.server = server
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield holder
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def client(stub: Stub) -> Iterator[Client]:
    with Client(stub.url) as api:
        yield api


def closed_port() -> int:
    """A loopback port with nothing listening on it."""

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


# --------------------------------------------------------------------------
# Config resolution (11 §Client connection)
# --------------------------------------------------------------------------


def config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_defaults_to_the_loopback_server() -> None:
    assert resolve(env={}, config_file=Path("/nonexistent/config.toml")) == (
        resolve(None, None, env={}, config_file=Path("/nonexistent/config.toml"))
    )
    resolved = resolve(env={}, config_file=Path("/nonexistent/config.toml"))
    assert resolved.url == DEFAULT_URL
    assert resolved.token is None


def test_arguments_beat_environment_beats_file(tmp_path: Path) -> None:
    stored = config(tmp_path, 'url = "http://file:1"\ntoken = "from-file"\n')
    env = {"ATHANORE_URL": "http://env:2", "ATHANORE_TOKEN": "from-env"}

    explicit = resolve("http://arg:3", "from-arg", env=env, config_file=stored)
    assert (explicit.url, explicit.token) == ("http://arg:3", "from-arg")

    from_env = resolve(env=env, config_file=stored)
    assert (from_env.url, from_env.token) == ("http://env:2", "from-env")

    from_file = resolve(env={}, config_file=stored)
    assert (from_file.url, from_file.token) == ("http://file:1", "from-file")


def test_each_half_resolves_on_its_own(tmp_path: Path) -> None:
    """A `--url` does not drop the token the file holds for it."""

    stored = config(tmp_path, 'url = "http://file:1"\ntoken = "from-file"\n')
    resolved = resolve("http://arg:3", env={}, config_file=stored)
    assert (resolved.url, resolved.token) == ("http://arg:3", "from-file")


def test_an_empty_environment_variable_is_not_an_answer(tmp_path: Path) -> None:
    stored = config(tmp_path, 'token = "from-file"\n')
    resolved = resolve(env={"ATHANORE_TOKEN": ""}, config_file=stored)
    assert resolved.token == "from-file"


def test_a_missing_config_file_is_not_an_error(tmp_path: Path) -> None:
    assert read_config(tmp_path / "nope.toml") == {}


def test_a_broken_config_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(ApiClientError, match="not valid TOML"):
        read_config(config(tmp_path, "url = "))
    with pytest.raises(ApiClientError, match="unknown key 'nope'"):
        read_config(config(tmp_path, 'nope = "x"\n'))
    with pytest.raises(ApiClientError, match="must be a string"):
        read_config(config(tmp_path, "url = 4002\n"))


def test_a_url_that_names_no_server_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ApiClientError, match="is not an http"):
        resolve(env={"ATHANORE_URL": "127.0.0.1:4002"}, config_file=tmp_path / "x")


def test_the_config_file_is_xdg_or_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg")
    assert config_path() == Path("/tmp/xdg/athanore/config.toml")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    monkeypatch.setenv("HOME", "/tmp/home")
    assert config_path() == Path("/tmp/home/.config/athanore/config.toml")


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------


def test_retries_are_connection_level_and_capped(client: Client) -> None:
    """AGENTS.md: connection-level httpx retries at most, and no more."""

    transport = client._http._transport
    assert isinstance(transport, httpx.HTTPTransport)
    assert transport._pool._retries == RETRIES == 2


def test_a_get_returns_the_decoded_body(stub: Stub, client: Client) -> None:
    stub.route("/api/runs", Reply(body=[{"run_id": "01H", "status": "queued"}]))
    assert client.get("/api/runs") == [{"run_id": "01H", "status": "queued"}]
    assert stub.last.method == "GET"
    assert "authorization" not in stub.last.headers


def test_a_token_is_sent_as_a_bearer(stub: Stub) -> None:
    stub.route("/api/runs", Reply(body=[]))
    with Client(stub.url, "sekret") as api:
        api.get("/api/runs")
    assert stub.last.headers["authorization"] == "Bearer sekret"


def test_params_drop_what_nobody_set(stub: Stub, client: Client) -> None:
    stub.route("/api/runs", Reply(body=[]))
    client.get("/api/runs", params={"status": "running", "workflow": None})
    assert stub.last.query == {"status": ["running"]}


def test_a_post_sends_json_and_reads_the_answer(stub: Stub, client: Client) -> None:
    stub.route("/api/workflows/demo/runs", Reply(201, {"run_id": "01H"}))
    answer = client.post("/api/workflows/demo/runs", {"title": "t"})
    assert answer == {"run_id": "01H"}
    assert json.loads(stub.last.body) == {"title": "t"}


def test_no_content_decodes_to_none(stub: Stub, client: Client) -> None:
    stub.route("/api/runs/01H", Reply(204))
    assert client.delete("/api/runs/01H") is None


def test_an_error_body_becomes_the_error_it_describes(
    stub: Stub, client: Client
) -> None:
    stub.route(
        "/api/runs/nope",
        Reply(404, {"error": "run not found", "code": "not_found"}),
    )
    with pytest.raises(ApiClientError) as caught:
        client.get("/api/runs/nope")
    assert str(caught.value) == "run not found"
    assert caught.value.status == 404
    assert caught.value.code == "not_found"


def test_a_validation_failure_carries_its_details(stub: Stub, client: Client) -> None:
    stub.route(
        "/api/workflows/demo/runs",
        Reply(
            422,
            {
                "error": "validation failed",
                "code": "validation",
                "errors": [{"loc": ["body", "title"], "msg": "field required"}],
            },
        ),
    )
    with pytest.raises(ApiClientError) as caught:
        client.post("/api/workflows/demo/runs", {})
    assert caught.value.details == ["body.title: field required"]


def test_a_body_that_is_not_the_error_shape_still_refuses(
    stub: Stub, client: Client
) -> None:
    stub.route(
        "/api/runs",
        Reply(502, text="<html>bad gateway</html>", content_type="text/html"),
    )
    with pytest.raises(ApiClientError, match="the server answered 502"):
        client.get("/api/runs")


def test_a_success_that_is_not_json_is_refused(stub: Stub, client: Client) -> None:
    stub.route("/api/runs", Reply(200, text="not json", content_type="text/plain"))
    with pytest.raises(ApiClientError, match="not JSON"):
        client.get("/api/runs")


def test_nothing_listening_is_a_transport_error() -> None:
    with Client(f"http://127.0.0.1:{closed_port()}") as api:
        with pytest.raises(httpx.ConnectError):
            api.get("/api/health")


# --------------------------------------------------------------------------
# The event stream
# --------------------------------------------------------------------------


FRAMES = (
    ": keep-alive\n\n",
    'id: 7\nevent: run.created\ndata: {"id": 7, "name": "run.created"}\n\n',
    'event: task.stream\ndata: {"name": "task.stream"}\n\n',
    'event: resync\ndata: {"reason":\ndata: "overflowed"}\n\n',
)


def test_events_are_parsed_frame_by_frame(stub: Stub, client: Client) -> None:
    stub.route("/api/events", Reply(sse=FRAMES))
    seen = list(client.events(after=3, names=["run.*", "task.*"], run="01H"))
    assert seen == [
        ServerEvent(name="run.created", data={"id": 7, "name": "run.created"}, id=7),
        # No `id:` line: an ephemeral event, so nothing to resume from.
        ServerEvent(name="task.stream", data={"name": "task.stream"}, id=None),
        # Two `data:` lines are one JSON document.
        ServerEvent(name="resync", data={"reason": "overflowed"}, id=None),
    ]
    assert stub.last.query == {
        "after": ["3"],
        "run": ["01H"],
        "names": ["run.*,task.*"],
    }


def test_events_send_no_filters_when_none_were_asked_for(
    stub: Stub, client: Client
) -> None:
    stub.route("/api/events", Reply(sse=("event: ping\ndata: {}\n\n",)))
    assert [event.name for event in client.events()] == ["ping"]
    assert stub.last.query == {}


def test_a_refused_stream_raises_before_any_frame(stub: Stub, client: Client) -> None:
    stub.route(
        "/api/events",
        Reply(401, {"error": "operator token required", "code": "unauthorized"}),
    )
    with pytest.raises(ApiClientError, match="operator token required") as caught:
        list(client.events())
    assert caught.value.status == 401


def test_a_frame_that_is_not_json_is_refused(stub: Stub, client: Client) -> None:
    stub.route("/api/events", Reply(sse=("event: run.created\ndata: nope\n\n",)))
    with pytest.raises(ApiClientError, match="not JSON"):
        list(client.events())


# --------------------------------------------------------------------------
# Output (11: a table on a TTY, JSON with --json)
# --------------------------------------------------------------------------


ROWS = [
    {"run_id": "01H", "status": "running", "workflow": {"name": "demo"}, "pool": None},
    {"run_id": "01J", "status": "queued", "workflow": {"name": "demo"}},
]
SPEC = (
    Column("Run", "run_id"),
    Column("Status", "status"),
    Column("Workflow", "workflow.name"),
    Column("Pool", "pool"),
)


def rendered(data: Any, spec: Any, json_flag: bool) -> str:
    console = Console(width=200, force_terminal=False)
    with console.capture() as capture:
        emit(data, spec, json_flag, console=console)
    return capture.get()


def test_a_table_shows_the_columns_it_was_given() -> None:
    text = rendered(ROWS, SPEC, False)
    header, first, second = (line.strip() for line in text.strip().splitlines())
    assert header.split() == ["Run", "Status", "Workflow", "Pool"]
    assert first.split() == ["01H", "running", "demo"]
    assert second.split() == ["01J", "queued", "demo"]


def test_json_is_the_whole_value_the_table_projected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    emit(ROWS, SPEC, True)
    printed = json.loads(capsys.readouterr().out)
    assert printed == ROWS
    table = rendered(ROWS, SPEC, False)
    for row in printed:
        assert row["run_id"] in table
        assert row["workflow"]["name"] in table


def test_an_empty_list_still_prints_its_headings() -> None:
    assert "Run" in rendered([], SPEC, False)


def test_text_without_a_spec_is_key_and_value() -> None:
    assert rendered({"run_id": "01H", "pool": None}, None, False) == (
        "run_id: 01H\npool: \n"
    )
    assert rendered(["01H", "01J"], None, False) == "01H\n01J\n"
    assert rendered("01H", None, False) == "01H\n"


# --------------------------------------------------------------------------
# Exit codes (11 §Exit codes)
# --------------------------------------------------------------------------


def stub_app(fail: Exception | None) -> typer.Typer:
    """A one-verb application whose verb raises ``fail``."""

    application = typer.Typer()

    @application.command()
    def go() -> None:
        if fail is not None:
            raise fail

    return application


def test_success_is_zero() -> None:
    assert dispatch(stub_app(None), []) == EXIT_OK
    assert main(["--help"]) == EXIT_OK


def test_an_api_error_is_one(capsys: pytest.CaptureFixture[str]) -> None:
    failure = ApiClientError(
        "validation failed",
        status=422,
        code="validation",
        body={"errors": [{"loc": ["body", "title"], "msg": "field required"}]},
    )
    assert dispatch(stub_app(failure), []) == EXIT_API_ERROR
    err = capsys.readouterr().err
    assert "validation failed" in err
    assert "body.title: field required" in err


def test_a_usage_mistake_is_two(stub: Stub, capsys: pytest.CaptureFixture[str]) -> None:
    # Named at the stub rather than left on the default loopback server:
    # the alias check is a real `GET /api/workflows`, so a developer with
    # an Athanore of their own on 4002 would otherwise have that one
    # answer it — and answer 401, which is exit 1.
    stub.route("/api/workflows", Reply(body=[]))
    assert main(["--url", stub.url, "no-such-verb"]) == EXIT_USAGE
    # T054's bare-workflow alias reports the unknown first word, because
    # it is the thing that knows a word can be a verb *or* a registered
    # workflow; click's own "No such command" would name only one of them.
    assert "is not an athanore verb" in " ".join(capsys.readouterr().err.split())
    assert main(["--url", "127.0.0.1:4002"]) == EXIT_USAGE
    assert "is not an http(s) URL" in capsys.readouterr().err
    # A bare `athanore` prints its help and is a usage error, as click's
    # own `no_args_is_help` reports it.
    assert main([]) == EXIT_USAGE


def test_an_unreachable_server_is_three(capsys: pytest.CaptureFixture[str]) -> None:
    port = closed_port()

    def unreachable() -> None:
        with Client(f"http://127.0.0.1:{port}") as api:
            api.get("/api/health")

    application = typer.Typer()
    application.command()(unreachable)
    assert dispatch(application, []) == EXIT_UNREACHABLE
    assert "ConnectError" in capsys.readouterr().err


def test_a_defect_is_not_an_exit_code() -> None:
    """Anything outside the three of 11 keeps its traceback."""

    with pytest.raises(ZeroDivisionError):
        dispatch(stub_app(ZeroDivisionError("boom")), [])


def test_options_build_the_client_they_describe() -> None:
    with Options(url="http://elsewhere:9", token="t").client() as api:
        assert api.url == "http://elsewhere:9"
        assert api.token == "t"


def test_the_global_flags_reach_the_verb() -> None:
    """The seam every verb of T053 onward reads its connection from."""

    seen: dict[str, Any] = {}
    application = typer.Typer()
    application.callback()(global_options)

    @application.command()
    def go(ctx: typer.Context) -> None:
        seen["options"] = ctx.obj

    argv = ["--url", "http://elsewhere:9", "--token", "t", "--json", "go"]
    assert dispatch(application, argv) == EXIT_OK
    assert seen["options"] == Options(url="http://elsewhere:9", token="t", json=True)
