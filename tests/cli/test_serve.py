"""The verbs that run or repair an installation (T053, 11 §Server).

Three of the four verbs here open a database or write a file, and the
fourth *is* the server, so this file is deliberately the least mocked in
the suite: `db` acts on real SQLite files, `token` and `login` are
checked by stat-ing what they wrote, and `serve` is started as a
**subprocess** and asked `/api/health` over a socket.

The subprocess is the point of the `serve` test rather than an accident
of it. `Server.serve()` owns an event loop and blocks; calling it in
process would either hang the suite or need the loop taken apart around
it, and neither would exercise the thing that can actually be wrong — a
bound port nobody was told about. So the CLI is spawned with
`python -m athanore.cli`, its first line of stdout is read for the URL it
printed, and every wait has a deadline: a watchdog kills the process, the
reads end at EOF, and a `serve` that hangs fails this test instead of
stalling the gate.

Every test here runs in `tmp_path` with `ATHANORE_*` scrubbed from the
environment and `XDG_CONFIG_HOME` moved, because all four verbs resolve
what they act on from exactly those two places: a suite that read the
developer's own `athanore.toml`, database or token file would be reading
the machine and not the code.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import tomllib
import webbrowser
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest
import structlog

from athanore.cli import main
from athanore.cli.client import read_config
from athanore.cli.output import EXIT_API_ERROR, EXIT_OK, EXIT_USAGE
from athanore.cli.serve import announce, layout, load_target
from athanore.server import Server
from athanore.settings import AthanoreSettings
from athanore.workflow import Workflow

#: The committed MVP database of T018, the input `db import-v0` takes.
V0_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "v0" / "mvp_small.sqlite3"
)

#: What one import of that fixture writes (`tests/store/test_legacy_import.py`).
V0_RUNS = 2

#: A workflow file, as an operator would write one next to their project.
WORKFLOW_FILE = '''\
from athanore.server import Server
from athanore.settings import AthanoreSettings
from athanore.workflow import Workflow

demo = Workflow("demo")


@demo.node(start=True)
async def only():
    """Do nothing, successfully."""
    return None


not_a_workflow = "text"
'''

#: How long the spawned server gets to bind, answer and stop. Generous
#: for a loopback server and finite, which is the only property that
#: matters: a hang fails one test rather than the run.
SERVE_TIMEOUT = 60.0


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A working directory, a config home and an environment of our own."""

    for name in [key for key in os.environ if key.startswith("ATHANORE_")]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture(autouse=True)
def reset_logging() -> Iterator[None]:
    """Undo the `configure_logging` a started server performs.

    The same fixture `tests/test_server.py` keeps, for the same reason:
    the handler binds to whatever `sys.stderr` is when it is built, and
    pytest swaps that stream between phases.
    """

    yield
    structlog.reset_defaults()
    logging.getLogger().handlers.clear()


@pytest.fixture(autouse=True)
def restore_imports() -> Iterator[None]:
    """Leave `sys.path` and `sys.modules` as they were.

    `serve path/to/file.py:wf` executes that file as a module and puts
    its directory on the path, which is what running it directly would
    have done. In a test process that is global state, so it is undone.
    """

    path = list(sys.path)
    modules = set(sys.modules)
    yield
    sys.path[:] = path
    for name in set(sys.modules) - modules:
        del sys.modules[name]


def sqlite_url(path: Path) -> str:
    """The database URL of a SQLite file at ``path``."""

    return f"sqlite+aiosqlite:///{path}"


def write_workflow(tmp_path: Path, name: str = "flows.py") -> Path:
    """A file with a `demo` workflow in it, and something that is not one."""

    path = tmp_path / name
    path.write_text(WORKFLOW_FILE)
    return path


# --------------------------------------------------------------------------
# serve
# --------------------------------------------------------------------------


@contextmanager
def spawn(
    tmp_path: Path,
    *args: str,
    timeout: float = SERVE_TIMEOUT,
    stderr: list[str] | None = None,
) -> Iterator[tuple[subprocess.Popen[str], str]]:
    """Run `athanore serve` as a subprocess and yield it and its URL.

    `python -m athanore.cli` rather than the installed console script:
    the entry point is the same function either way, and the module form
    does not depend on the script having been regenerated by the most
    recent install.

    What the process said on stderr is only whole once it has stopped, so
    a caller that wants it passes a list to collect it into and reads it
    after the block.
    """

    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("ATHANORE_")
    }
    process = subprocess.Popen(
        [sys.executable, "-m", "athanore.cli", "serve", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(tmp_path),
        env=environment,
    )
    # The deadline. Killing the process is what makes every read below
    # end: `readline` returns "" at EOF rather than blocking for ever.
    watchdog = threading.Timer(timeout, process.kill)
    watchdog.start()
    try:
        yield process, read_url(process)
    finally:
        watchdog.cancel()
        said = shutdown(process)
        if stderr is not None:
            stderr.append(said)


def read_url(process: subprocess.Popen[str]) -> str:
    """The URL `serve` printed, or a failure carrying what it said instead."""

    assert process.stdout is not None
    while True:
        line = process.stdout.readline()
        if not line:
            process.kill()
            stderr = process.stderr.read() if process.stderr else ""
            raise AssertionError(f"serve printed no URL before exiting: {stderr}")
        if "http://" in line:
            return "http://" + line.split("http://", 1)[1].strip()


def shutdown(process: subprocess.Popen[str]) -> str:
    """Stop the server the way an operator would, and return its stderr."""

    if process.poll() is None:
        process.terminate()
    try:
        _, said = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        process.kill()
        _, said = process.communicate()
    return said or ""


def test_serve_binds_and_answers_health(tmp_path: Path) -> None:
    """`serve path.py:wf --port 0` serves the workflow it was given."""

    write_workflow(tmp_path)
    with spawn(
        tmp_path,
        "flows.py:demo",
        "--port",
        "0",
        "--host",
        "127.0.0.1",
        "--no-discover",
    ) as (process, url):
        health = httpx.get(f"{url}/api/health", timeout=30.0)
        workflows = httpx.get(f"{url}/api/workflows", timeout=30.0)
    assert health.status_code == 200
    assert health.json()["ok"] is True
    assert "demo" in [wf["name"] for wf in workflows.json()]
    # A terminated server stops gracefully and says so with its status.
    assert process.returncode == EXIT_OK


def test_serve_reads_pools_from_athanore_toml(tmp_path: Path) -> None:
    """`[pools]` and `[workflows]` bind the workflow to a declared pool."""

    write_workflow(tmp_path)
    (tmp_path / "athanore.toml").write_text(
        '[pools]\nlocal = 3\ncloud = 8\n\n[workflows]\ndemo = { pool = "local" }\n'
    )
    with spawn(tmp_path, "flows.py:demo", "--port", "0", "--no-discover") as (_, url):
        pools = httpx.get(f"{url}/api/health", timeout=30.0).json()["pools"]
    # Only the pool a registered workflow was bound to: `cloud` is
    # declared and unused, and an unused cap is not a pool that exists.
    assert pools == {"local": {"capacity": 3, "in_flight": 0}}


def test_serve_sizes_the_default_pool_with_workers(tmp_path: Path) -> None:
    """A workflow nobody bound runs on the default pool, sized by `--workers`."""

    write_workflow(tmp_path)
    with spawn(
        tmp_path, "flows.py:demo", "--port", "0", "--workers", "4", "--no-discover"
    ) as (_, url):
        pools = httpx.get(f"{url}/api/health", timeout=30.0).json()["pools"]
    assert pools == {"default": {"capacity": 4, "in_flight": 0}}


def test_a_file_target_is_executed_and_its_directory_is_importable(
    tmp_path: Path,
) -> None:
    """`path/to/file.py:wf` runs the file, as running it directly would."""

    (tmp_path / "helper.py").write_text("NAME = 'demo'\n")
    (tmp_path / "flows.py").write_text(
        "from athanore.workflow import Workflow\n"
        "from helper import NAME\n"
        "\n"
        "demo = Workflow(NAME)\n"
        "\n"
        "@demo.node(start=True)\n"
        "async def only():\n"
        "    return None\n"
    )
    workflow = load_target("flows.py:demo")
    assert isinstance(workflow, Workflow)
    assert workflow.name == "demo"


def test_a_module_target_is_imported(tmp_path: Path) -> None:
    """`module:wf` imports the module, with the working directory on the path."""

    write_workflow(tmp_path, "project_flows.py")
    assert load_target("project_flows:demo").name == "demo"


@pytest.mark.parametrize(
    "target",
    [
        "flows.py",  # no attribute
        "flows.py:missing",  # no such attribute
        "flows.py:not_a_workflow",  # not a Workflow
        "nowhere.py:demo",  # no such file
        "no_such_module:demo",  # no such module
    ],
)
def test_a_target_that_names_nothing_is_a_usage_error(
    tmp_path: Path, target: str
) -> None:
    """Every way of mistyping a target costs 2, never a traceback."""

    write_workflow(tmp_path)
    assert main(["serve", target, "--port", "0"]) == EXIT_USAGE


def test_a_workflow_bound_to_an_undeclared_pool_is_a_usage_error(
    tmp_path: Path,
) -> None:
    """A `[workflows]` entry naming a pool `[pools]` does not have."""

    write_workflow(tmp_path)
    (tmp_path / "athanore.toml").write_text(
        '[pools]\nlocal = 1\n\n[workflows]\ndemo = { pool = "sandbox" }\n'
    )
    assert main(["serve", "flows.py:demo", "--port", "0"]) == EXIT_USAGE


@pytest.mark.parametrize(
    "toml",
    [
        "[pools]\nlocal = true\n",  # a capacity that is not an integer
        '[workflows]\ndemo = { poll = "local" }\n',  # an unknown key
        "[workflows]\ndemo = 1\n",  # not a table
        "[pools]\nlocal = 1\n[workflows]\ndemo = { pool = 2 }\n",  # not a name
    ],
)
def test_athanore_toml_that_cannot_be_used_is_refused(
    tmp_path: Path, toml: str
) -> None:
    """02: a typo must not silently fall back to a default."""

    write_workflow(tmp_path)
    (tmp_path / "athanore.toml").write_text(toml)
    assert main(["serve", "flows.py:demo", "--port", "0"]) == EXIT_USAGE


def test_layout_reads_both_tables_and_tolerates_neither(tmp_path: Path) -> None:
    """`layout` is the whole of what `serve` takes from `athanore.toml`."""

    assert layout(tmp_path) == ({}, {})
    (tmp_path / "athanore.toml").write_text(
        "host = '127.0.0.1'\n\n"
        "[pools]\nlocal = 1\ncloud = 8\n\n"
        "[workflows]\n"
        'feature_build = { pool = "local" }\n'
        "msgtest = { }\n"
    )
    capacities, bindings = layout(tmp_path)
    assert capacities == {"local": 1, "cloud": 8}
    # `msgtest` named no pool, so it is absent rather than bound to a
    # name nobody wrote: the engine's default pool is what it gets.
    assert bindings == {"feature_build": "local"}


def test_a_workflow_name_that_shadows_a_verb_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A registration a `Server` refuses is a sentence, not a traceback."""

    (tmp_path / "flows.py").write_text(
        "from athanore.workflow import Workflow\n"
        "\n"
        'demo = Workflow("ls")\n'
        "\n"
        "@demo.node(start=True)\n"
        "async def only():\n"
        "    return None\n"
    )
    assert main(["serve", "flows.py:demo", "--port", "0"]) == EXIT_API_ERROR
    assert "verb" in capsys.readouterr().err


def test_a_binding_for_a_workflow_that_is_not_served_is_a_warning(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """It is said once and it is not fatal: the serve goes on to bind."""

    write_workflow(tmp_path)
    (tmp_path / "athanore.toml").write_text(
        '[pools]\nlocal = 1\n\n[workflows]\nother = { pool = "local" }\n'
    )
    said: list[str] = []
    with spawn(
        tmp_path, "flows.py:demo", "--port", "0", "--no-discover", stderr=said
    ) as (_, url):
        assert httpx.get(f"{url}/api/health", timeout=30.0).json()["ok"] is True
    assert "Warning" in said[0]
    assert "other" in said[0]


def test_open_points_a_browser_at_the_url_that_was_printed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`--open` and the printed line are the same string, by construction."""

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url) or True)
    server = Server(AthanoreSettings(root_path=tmp_path, host="127.0.0.1", port=4002))

    announce(server, open_browser=True)

    printed = capsys.readouterr().out
    assert server.url in printed
    assert opened == [server.url]


def test_a_network_bind_without_a_token_is_reported_not_traced(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """12 §Operator token, as the operator sees it from a command line."""

    write_workflow(tmp_path)
    status = main(["serve", "flows.py:demo", "--host", "0.0.0.0", "--port", "0"])
    assert status == EXIT_API_ERROR
    assert "token" in capsys.readouterr().err.lower()


# --------------------------------------------------------------------------
# token, login
# --------------------------------------------------------------------------


def mode_of(path: Path) -> int:
    """The permission bits of ``path``."""

    return path.stat().st_mode & 0o777


def test_token_rotate_writes_0600_in_a_fresh_directory(tmp_path: Path) -> None:
    """`.athanore/` is created, and the token in it is the owner's alone."""

    assert main(["token", "rotate"]) == EXIT_OK
    token_file = tmp_path / ".athanore" / "token"
    assert mode_of(token_file) == 0o600
    assert mode_of(token_file.parent) == 0o700
    assert token_file.read_text().strip()


def test_token_rotate_narrows_a_file_that_was_already_wide(tmp_path: Path) -> None:
    """A rotation into an existing, world-readable token file fixes the mode."""

    token_file = tmp_path / ".athanore" / "token"
    token_file.parent.mkdir()
    token_file.write_text("old-token\n")
    os.chmod(token_file, 0o644)

    assert main(["token", "rotate"]) == EXIT_OK
    assert mode_of(token_file) == 0o600
    assert token_file.read_text().strip() != "old-token"


def test_token_show_reports_the_stored_token(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """What `rotate` wrote is what `show` prints."""

    assert main(["--json", "token", "rotate"]) == EXIT_OK
    rotated = json.loads(capsys.readouterr().out)

    assert main(["--json", "token", "show"]) == EXIT_OK
    shown = json.loads(capsys.readouterr().out)
    assert shown["token"] == rotated["token"]
    assert shown["source"] == "file"


def test_token_show_without_one_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing is invented: an absent token is reported, never generated."""

    assert main(["token", "show"]) == EXIT_API_ERROR
    assert "rotate" in capsys.readouterr().err
    assert not (tmp_path / ".athanore").exists()


def test_login_stores_the_connection_0600(tmp_path: Path) -> None:
    """11 §Client connection: the url and token the client falls back to."""

    url = "http://athanore.example:4002"
    assert main(["login", url, "--token", "  secret-token  "]) == EXIT_OK
    config = tmp_path / "xdg" / "athanore" / "config.toml"
    assert mode_of(config) == 0o600
    # Read back through the client's own reader: a file this verb wrote
    # is a file `resolve()` accepts, keys and all.
    assert read_config(config) == {"url": url, "token": "secret-token"}


def test_login_prompts_when_no_token_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token is typed, hidden, rather than left in shell history."""

    monkeypatch.setattr("typer.prompt", lambda *args, **kwargs: "typed-token")
    assert main(["login", "http://127.0.0.1:4002"]) == EXIT_OK
    stored = read_config(tmp_path / "xdg" / "athanore" / "config.toml")
    assert stored["token"] == "typed-token"


def test_login_quotes_what_it_writes(tmp_path: Path) -> None:
    """A token with a quote in it round trips rather than breaking the file."""

    token = 'a"b\\c'
    assert main(["login", "http://127.0.0.1:4002", "--token", token]) == EXIT_OK
    config = tmp_path / "xdg" / "athanore" / "config.toml"
    assert tomllib.loads(config.read_text())["token"] == token


@pytest.mark.parametrize("url", ["127.0.0.1:4002", "ftp://host", "notaurl"])
def test_login_refuses_a_url_that_is_not_one(tmp_path: Path, url: str) -> None:
    """The usage error 11 §Exit codes prices at 2."""

    assert main(["login", url, "--token", "x"]) == EXIT_USAGE


# --------------------------------------------------------------------------
# db
# --------------------------------------------------------------------------


def test_db_upgrade_then_current_reports_the_revision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """07 §Migrations, driven by hand instead of by a starting server."""

    assert main(["--json", "db", "current"]) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["revision"] is None

    assert main(["db", "upgrade"]) == EXIT_OK
    capsys.readouterr()
    assert main(["--json", "db", "current"]) == EXIT_OK
    reported = json.loads(capsys.readouterr().out)
    assert reported["revision"]
    # The database the configured URL names, which is the one a `serve`
    # in this directory would have opened.
    assert (tmp_path / "athanore.db").is_file()
    assert reported["db_url"].endswith(str(tmp_path / "athanore.db"))


def test_db_upgrade_refuses_a_v0_database(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """07: an MVP database is imported, never migrated in place."""

    mvp = tmp_path / "athanore.db"
    mvp.write_bytes(V0_FIXTURE.read_bytes())

    assert main(["db", "upgrade"]) == EXIT_API_ERROR
    assert "import-v0" in capsys.readouterr().err
    # Untouched: no `alembic_version`, and the MVP's tables as they were.
    assert "alembic_version" not in table_names(mvp)
    assert run_count(mvp) == V0_RUNS


def test_db_import_v0_carries_the_fixture_over(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """07 §Importing a v0 database, from the command line (T018's fixture)."""

    destination = tmp_path / "imported.db"
    status = main(
        ["--json", "db", "import-v0", str(V0_FIXTURE), "--db", sqlite_url(destination)]
    )
    assert status == EXIT_OK
    report = json.loads(capsys.readouterr().out)
    assert report["runs"] == V0_RUNS
    assert report["tasks"] == 6
    assert report["skipped_runs"] == []
    assert run_count(destination) == V0_RUNS

    # Idempotent: the second pass writes nothing and says which runs it
    # already had (07).
    assert (
        main(
            [
                "--json",
                "db",
                "import-v0",
                str(V0_FIXTURE),
                "--db",
                sqlite_url(destination),
            ]
        )
        == EXIT_OK
    )
    again = json.loads(capsys.readouterr().out)
    assert again["runs"] == 0
    assert len(again["skipped_runs"]) == V0_RUNS


def test_db_import_v0_refuses_a_source_that_is_not_there(tmp_path: Path) -> None:
    """A path that names no file is a usage error, not a traceback."""

    assert main(["db", "import-v0", str(tmp_path / "nope.db")]) == EXIT_USAGE


def test_db_backup_copies_a_live_database(tmp_path: Path) -> None:
    """07 §Backups: the SQLite backup API, not a file copy."""

    source = tmp_path / "athanore.db"
    assert main(["db", "import-v0", str(V0_FIXTURE), "--db", sqlite_url(source)]) == 0
    # A connection held open across the backup is the case `cp` gets
    # wrong: the copy must be consistent while something else is
    # attached to the database.
    live = sqlite3.connect(source)
    try:
        destination = tmp_path / "backup.db"
        assert main(["db", "backup", str(destination)]) == EXIT_OK
        assert mode_of(destination) == 0o600
        assert run_count(destination) == run_count(source)
    finally:
        live.close()


def test_db_backup_never_overwrites(tmp_path: Path) -> None:
    """A destination that exists is refused; a backup destroys nothing."""

    source = tmp_path / "athanore.db"
    assert main(["db", "upgrade", "--db", sqlite_url(source)]) == EXIT_OK
    destination = tmp_path / "backup.db"
    destination.write_text("not a database")

    assert main(["db", "backup", str(destination)]) == EXIT_USAGE
    assert destination.read_text() == "not a database"


def test_db_backup_refuses_a_database_it_cannot_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The backup API is SQLite's; another backend is told so."""

    status = main(
        [
            "db",
            "backup",
            str(tmp_path / "backup.db"),
            "--db",
            "postgresql+asyncpg://user@localhost/athanore",
        ]
    )
    assert status == EXIT_API_ERROR
    assert "postgresql" in capsys.readouterr().err
    assert not (tmp_path / "backup.db").exists()


def test_db_backup_of_a_database_that_is_not_there(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Nothing to copy is reported, and no empty file is created."""

    assert main(["db", "backup", str(tmp_path / "backup.db")]) == EXIT_API_ERROR
    # Whitespace-normalised: the console wraps a long path, and the
    # sentence is what is being asserted, not where it broke.
    assert "does not exist" in " ".join(capsys.readouterr().err.split())
    assert not (tmp_path / "backup.db").exists()
    # The question did not create the database it asked about.
    assert not (tmp_path / "athanore.db").exists()


def table_names(path: Path) -> set[str]:
    """Every table in a SQLite database at ``path``."""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    finally:
        connection.close()
    return {str(row[0]) for row in rows}


def run_count(path: Path) -> int:
    """How many runs a SQLite database at ``path`` holds."""

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return int(connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0])
    finally:
        connection.close()


# --------------------------------------------------------------------------
# the entry point
# --------------------------------------------------------------------------


def test_the_console_script_names_the_cli(tmp_path: Path) -> None:
    """`[project.scripts]` and `python -m athanore.cli` are one function."""

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    scripts = tomllib.loads(pyproject.read_text())["project"]["scripts"]
    assert scripts == {"athanore": "athanore.cli:main"}
    assert callable(main)
