"""`athanore workflows add|reload|rm` against a served process (T086, 22 §CLI).

The three verbs are thin clients of `POST`, `PUT` and `DELETE
/api/workflows`, so what these tests check is the CLI's half of the
contract: the body each sends, what each prints (the entry, the ids,
the receipt), the exit codes 22 §CLI prices — 2 for a load that failed
or a pool the server does not have, 1 for the server's other refusals —
and that `--json` leaves stdout as the API's own JSON. The server's side
of the same verbs is `tests/api/test_registration_api.py`.

The `cli`, `server` and `api` fixtures are `tests/cli/conftest.py`'s;
the two autouse fixtures below are copied from `tests/test_server.py`,
because `load_target` edits `sys.modules` and `sys.path` and no verb may
ever write a workflow's `.py`.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from athanore.cli.output import EXIT_API_ERROR, EXIT_OK, EXIT_USAGE
from athanore.server import Server
from tests.cli.conftest import Api, Cli, flat, until

# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def restore_imports() -> Iterator[None]:
    """`load_target` on a file target edits `sys.modules` and `sys.path`."""

    path = list(sys.path)
    modules = set(sys.modules)
    yield
    sys.path[:] = path
    for name in set(sys.modules) - modules:
        del sys.modules[name]


#: The digest of every `.py` the running test wrote, keyed by path.
_written: dict[Path, str] = {}


@pytest.fixture(autouse=True)
def sources_are_never_written() -> Iterator[None]:
    """22 §Persistence, "Never the source": every `.py` is byte-identical."""

    _written.clear()
    yield
    for path, digest in _written.items():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path


def write_target(
    tmp_path: Path, stem: str, name: str, node: str = "only", *, park: bool = False
) -> str:
    """A one-node workflow file under `tmp_path`, and the target naming it."""

    path = tmp_path / f"{stem}.py"
    body = "    await asyncio.sleep(3600)\n" if park else ""
    path.write_text(
        ("import asyncio\n" if park else "")
        + "from athanore.workflow import Workflow\n"
        "\n"
        f'wf = Workflow("{name}")\n'
        "\n"
        "\n"
        "@wf.node(start=True)\n"
        f"async def {node}():\n"
        f"{body}"
        "    return None\n"
    )
    _written[path] = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"{path}:wf"


# --------------------------------------------------------------------------
# workflows (the table)
# --------------------------------------------------------------------------


async def test_the_bare_verb_is_the_table_and_shows_a_target_only_when_there_is_one(
    tmp_path: Path, cli: Cli
) -> None:
    """The table verb is unchanged for programmatic registrations."""

    result = await cli.run("workflows")
    assert result.code == EXIT_OK
    assert "demo  start=plan  pool=default 0/4" in result.out
    assert "target=" not in result.out

    target = write_target(tmp_path, "hello", "hello")
    assert (await cli.run("workflows", "add", target)).code == EXIT_OK
    result = await cli.run("workflows")
    assert result.code == EXIT_OK
    assert f"hello start=only pool=default 0/4 target={target}" in flat(result.out)
    assert "demo  start=plan  pool=default 0/4\n" in result.out


# --------------------------------------------------------------------------
# add
# --------------------------------------------------------------------------


async def test_add_registers_and_prints_the_entry(
    tmp_path: Path, cli: Cli, api: Api, server: Server
) -> None:
    """`POST /api/workflows`, then the entry as the table prints one."""

    target = write_target(tmp_path, "hello", "hello")
    result = await cli.run("workflows", "add", target)
    assert result.code == EXIT_OK, result.err
    assert f"hello start=only pool=default 0/4 target={target}" in flat(result.out)
    assert "(terminal)" in result.out
    assert "persisted to" not in result.out
    listed = await api.get("/api/workflows")
    assert [wf["name"] for wf in listed if wf["name"] == "hello"] == ["hello"]
    assert not server.toml_path.exists()


async def test_add_with_json_prints_the_workflow_out(tmp_path: Path, cli: Cli) -> None:
    target = write_target(tmp_path, "hello", "hello")
    body = await cli.json("workflows", "add", target)
    assert body["name"] == "hello"
    assert body["target"] == target
    assert list(body["nodes"]) == ["only"]


async def test_add_of_a_registered_name_is_the_servers_refusal(
    tmp_path: Path, cli: Cli
) -> None:
    """409 `conflict` is exit 1 with the server's sentence on stderr."""

    target = write_target(tmp_path, "hello", "hello")
    assert (await cli.run("workflows", "add", target)).code == EXIT_OK
    again = await cli.run("workflows", "add", target)
    assert again.code == EXIT_API_ERROR
    assert "workflow 'hello' is already registered" in flat(again.err)
    assert again.out == ""


async def test_add_of_a_broken_target_exits_2_with_the_stage(
    tmp_path: Path, cli: Cli
) -> None:
    """22 §CLI: `workflow_load_failed` prints `stage` and `detail`, exit 2."""

    target = write_target(tmp_path, "hello", "hello").replace(":wf", ":missing")
    result = await cli.run("workflows", "add", target)
    assert result.code == EXIT_USAGE
    assert "has no attribute 'missing'" in flat(result.err)
    assert "attribute: " in flat(result.err)
    assert result.out == ""

    result = await cli.run("workflows", "add", "nocolon")
    assert result.code == EXIT_USAGE
    assert "target: " in flat(result.err)


async def test_add_names_the_pool_and_refuses_an_unknown_one(
    tmp_path: Path, cli: Cli
) -> None:
    """`--pool` is the body's `pool`; an unknown one is exit 2 naming the known."""

    target = write_target(tmp_path, "hello", "hello")
    refused = await cli.run("workflows", "add", target, "--pool", "nope")
    assert refused.code == EXIT_USAGE
    assert "no pool named 'nope'" in flat(refused.err)
    assert "'holding'" in flat(refused.err)
    bound = await cli.json("workflows", "add", target, "--pool", "holding")
    assert bound["pool"] == "holding"


# --------------------------------------------------------------------------
# reload
# --------------------------------------------------------------------------


async def test_reload_with_and_without_a_target(
    tmp_path: Path, cli: Cli, api: Api
) -> None:
    target = write_target(tmp_path, "hello", "hello", "first")
    assert (await cli.run("workflows", "add", target)).code == EXIT_OK

    write_target(tmp_path, "hello", "hello", "second")
    result = await cli.run("workflows", "reload", "hello")
    assert result.code == EXIT_OK, result.err
    assert "second" in result.out
    assert list((await api.get("/api/workflows/hello"))["nodes"]) == ["second"]

    other = write_target(tmp_path, "hello2", "hello", "third")
    body = await cli.json("workflows", "reload", "hello", other)
    assert list(body["nodes"]) == ["third"]
    assert body["target"] == other


async def test_reload_of_a_programmatic_workflow_needs_a_target(cli: Cli) -> None:
    """`stage: "target"` is exit 2 too; with a target it is an ordinary reload."""

    result = await cli.run("workflows", "reload", "demo")
    assert result.code == EXIT_USAGE
    assert "no recorded target" in flat(result.err)
    assert "target: " in flat(result.err)


async def test_reload_of_an_unknown_workflow_is_the_servers_404(cli: Cli) -> None:
    result = await cli.run("workflows", "reload", "nope")
    assert result.code == EXIT_API_ERROR
    assert "not registered" in flat(result.err)


# --------------------------------------------------------------------------
# rm
# --------------------------------------------------------------------------


async def test_rm_prints_the_interrupted_task_ids(
    tmp_path: Path, cli: Cli, api: Api, server: Server
) -> None:
    """22 §CLI: one id per line, so the operator sees what stopped."""

    target = write_target(tmp_path, "held", "held", "hold", park=True)
    assert (await cli.run("workflows", "add", target)).code == EXIT_OK
    run_id = await api.submit("held", "parks")
    await until(lambda: server.engine.attempts_of("held"), what="the attempt to park")
    task_ids = server.engine.attempts_of("held")

    result = await cli.run("workflows", "rm", "held")
    assert result.code == EXIT_OK, result.err
    assert result.out.split() == [str(task_id) for task_id in task_ids]
    run = await api.run(run_id)
    assert run["unregistered"] is True
    assert "held" not in [wf["name"] for wf in await api.get("/api/workflows")]


async def test_rm_of_a_quiet_workflow_prints_nothing(
    tmp_path: Path, cli: Cli, api: Api
) -> None:
    target = write_target(tmp_path, "hello", "hello")
    assert (await cli.run("workflows", "add", target)).code == EXIT_OK
    result = await cli.run("workflows", "rm", "hello")
    assert result.code == EXIT_OK, result.err
    assert result.out == ""
    body = await cli.json("workflows", "add", target)
    assert body["name"] == "hello"
    assert await cli.json("workflows", "rm", "hello") == {
        "workflow": "hello",
        "task_ids": [],
    }


async def test_rm_of_an_unknown_workflow_is_the_servers_404(cli: Cli) -> None:
    result = await cli.run("workflows", "rm", "nope")
    assert result.code == EXIT_API_ERROR
    assert "not registered" in flat(result.err)


# --------------------------------------------------------------------------
# --persist
# --------------------------------------------------------------------------

ORIGINAL = "# keep me\n\n[workflows]\ndemo = { }   # theirs\n"


async def test_persist_writes_the_row_and_prints_the_path(
    tmp_path: Path, cli: Cli, api: Api, server: Server
) -> None:
    """Each verb with `--persist` changes its row and prints the receipt."""

    toml = server.toml_path
    toml.write_text(ORIGINAL)
    target = write_target(tmp_path, "hello", "hello")

    added = await cli.run("workflows", "add", target, "--persist", "--pool", "holding")
    assert added.code == EXIT_OK, added.err
    assert flat(added.out).endswith(f"persisted to {toml}")
    assert toml.read_text() == ORIGINAL + (
        f'hello = {{ target = "{target}", pool = "holding" }}\n'
    )

    reloaded = await cli.run("workflows", "reload", "hello", "--persist")
    assert reloaded.code == EXIT_OK, reloaded.err
    assert flat(reloaded.out).endswith(f"persisted to {toml}")
    assert toml.read_text() == ORIGINAL + f'hello = {{ target = "{target}" }}\n'

    removed = await cli.run("workflows", "rm", "hello", "--persist")
    assert removed.code == EXIT_OK, removed.err
    assert flat(removed.out) == f"removed from {toml}"
    assert toml.read_text() == ORIGINAL

    # Without a row to remove there is no receipt (D244).
    assert (await cli.run("workflows", "add", target)).code == EXIT_OK
    quiet = await cli.run("workflows", "rm", "hello", "--persist")
    assert quiet.code == EXIT_OK
    assert quiet.out == ""
    assert toml.read_text() == ORIGINAL


async def test_under_json_the_receipt_is_on_stderr(
    tmp_path: Path, cli: Cli, api: Api, server: Server
) -> None:
    """D252: stdout is the API's JSON and parses; the path is on stderr."""

    toml = server.toml_path
    target = write_target(tmp_path, "hello", "hello")
    result = await cli.run("workflows", "add", target, "--persist", json=True)
    assert result.code == EXIT_OK, result.err
    assert json.loads(result.out)["name"] == "hello"
    assert flat(result.err) == f"persisted to {toml}"
    assert toml.exists()

    result = await cli.run("workflows", "rm", "hello", "--persist", json=True)
    assert result.code == EXIT_OK, result.err
    assert json.loads(result.out) == {"workflow": "hello", "task_ids": []}
    assert flat(result.err) == f"removed from {toml}"


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes read-only files")
async def test_a_write_that_fails_is_exit_1_with_the_servers_message(
    tmp_path: Path, cli: Cli, api: Api, server: Server
) -> None:
    toml = server.toml_path
    toml.write_text(ORIGINAL)
    toml.chmod(stat.S_IRUSR)
    target = write_target(tmp_path, "hello", "hello")
    try:
        result = await cli.run("workflows", "add", target, "--persist")
        assert result.code == EXIT_API_ERROR
        assert "was not updated and the registration was not changed" in flat(
            result.err
        )
        assert "hello" not in [wf["name"] for wf in await api.get("/api/workflows")]
    finally:
        toml.chmod(stat.S_IRUSR | stat.S_IWUSR)
