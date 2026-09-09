"""The two vendor adapters of T076, and the two checks they are (A6.1).

`claude_acp` and `docker_acp` are the examples that exist to say
something about an *adapter* rather than about a pipeline: one points the
façade at a second vendor's ACP implementation, the other points it into
the dev stack's container. What is assertable about either is what it
declares — the pinned command, the tier, the policy, the provider — plus
the deterministic halves of each workflow, which are the halves that
carry a verdict.

The bodies are run with real :class:`~athanore.graph.EdgeRef` arguments
and what comes back goes through
:func:`~athanore.engine.routing.interpret`, as in the other example
suites. Nothing here spawns an agent: the seats' declarations are class
attributes, and the two nodes that are not agents are code.
"""

from __future__ import annotations

import re
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import claude_acp
import docker_acp
import pytest
import yaml
from claude_acp import ClaudeAgent, ImplementerAgent
from docker_acp import DockerAgent

import projects
from athanore import NonRetryable
from athanore.agents.acp import ACPAgent
from athanore.engine.context import TaskContext, bind
from athanore.engine.routing import interpret
from athanore.graph import EdgeRef, Graph, Node
from athanore.plugins.discovery import discover
from athanore.settings import AthanoreSettings
from athanore.store.rows import LogAuthor, LogKind
from athanore.store.uow import Store
from pi import PiAgent, PiSessionStats

ROOT = Path(__file__).resolve().parents[2]

CLAUDE_GRAPH: Graph = claude_acp.wf.finalize()
DOCKER_GRAPH: Graph = docker_acp.wf.finalize()

#: `athanore-examples`, as `importlib.metadata` sees it.
DISTRIBUTION = "athanore-examples"
GROUP = "athanore.workflows"


def compose() -> dict[str, Any]:
    """`compose.yaml`, parsed: the one definition of the sandbox (D64)."""

    return yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))


async def route(graph: Graph, name: str, payload: Any = None) -> list[Any]:
    """Run node ``name``'s body and interpret what it returned."""

    one: Node = graph.nodes[name]
    slot = {one.payload_param: payload} if one.payload_param else {}
    value = await one.fn(*(EdgeRef(edge) for edge in one.edges), **slot)
    return [(step.target, step.payload) for step in interpret(one, value)]


# --------------------------------------------------------------------------
# The exit condition of T076: both import, and both finalize
# --------------------------------------------------------------------------


def test_both_workflows_finalize() -> None:
    """Rule 1: the signature is the graph, and both graphs are legal.

    `claude_acp` is a two-node check — one agent, one deterministic
    verdict — and `docker_acp` is the single node that is the whole
    point of it: an agent, in a container, and whatever it leaves behind.
    """

    assert CLAUDE_GRAPH.name == "claude_acp"
    assert CLAUDE_GRAPH.start == "implement"
    assert {name: one.edges for name, one in CLAUDE_GRAPH.nodes.items()} == {
        "implement": ("wrap",),
        "wrap": (),
    }

    assert DOCKER_GRAPH.name == "docker_acp"
    assert DOCKER_GRAPH.start == "implement"
    assert {name: one.edges for name, one in DOCKER_GRAPH.nodes.items()} == {
        "implement": ()
    }


def test_athanore_serve_discovers_both() -> None:
    """`athanore serve` needs to be told nothing (09 §Discovery)."""

    advertised = {
        entry.name: entry.value
        for entry in entry_points(group=GROUP)
        if entry.dist is not None and entry.dist.name == DISTRIBUTION
    }
    assert advertised["claude_acp"] == "claude_acp:wf"
    assert advertised["docker_acp"] == "docker_acp:wf"

    found = {workflow.name: workflow for workflow in discover()}
    assert found["claude_acp"] is claude_acp.wf
    assert found["docker_acp"] is docker_acp.wf


# --------------------------------------------------------------------------
# claude_acp: a command and a model, and nothing else
# --------------------------------------------------------------------------


def test_the_claude_seat_is_configuration_and_not_a_second_facade() -> None:
    """05 §User-land adapters: command + model only, and no code path.

    The value of this example is that there is nothing Claude-specific
    anywhere — permissions, config options, the tier and the environment
    scrub are all the generic ACP code's (20 §Findings 1-4). A seat that
    declared a fourth thing would be the beginning of the fork.
    """

    assert issubclass(ClaudeAgent, ACPAgent)
    declared = {name for name in vars(ClaudeAgent) if not name.startswith("__")}
    assert declared == {"command", "model", "stats_provider"}


def test_the_claude_adapter_is_pinned() -> None:
    """12 §Supply chain: an example pins, it does not float."""

    assert ClaudeAgent.command == [
        "npx",
        "-y",
        f"@agentclientprotocol/claude-agent-acp@{claude_acp.CLAUDE_ACP_VERSION}",
    ]
    assert re.fullmatch(r"\d+\.\d+\.\d+", claude_acp.CLAUDE_ACP_VERSION)


def test_the_pinned_adapter_is_the_sandboxs_and_the_one_projects_runs() -> None:
    """One pin, in three places, or two of them are stale.

    `compose.yaml` builds the adapter into the dev image, `projects` runs
    its seats on it, and this example checks it. The version literal is
    written in each of the three because none of them can import the
    others — an example must not depend on the dev stack, and a workflow
    must not depend on another workflow for its vendor pin — so what
    keeps them equal is this assertion.
    """

    raw = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    found = re.search(r"CLAUDE_ACP_VERSION:\s*\$\{CLAUDE_ACP_VERSION:-([\d.]+)\}", raw)
    assert found is not None, "compose.yaml no longer pins CLAUDE_ACP_VERSION"
    assert found.group(1) == claude_acp.CLAUDE_ACP_VERSION
    assert projects.CLAUDE_ACP_VERSION == claude_acp.CLAUDE_ACP_VERSION
    assert projects.CLAUDE == ClaudeAgent.command


def test_the_claude_seat_reports_no_stats_it_cannot_read() -> None:
    """`AGENTS.md` §Real data only: unknown is omitted, not estimated.

    Claude Code keeps no session file this repository knows how to read,
    so there is no provider — where pi has one, and the difference is
    the point (D27).
    """

    assert ClaudeAgent.stats_provider is None
    assert isinstance(PiAgent.stats_provider, PiSessionStats)


def test_the_claude_seat_negotiates_its_tier_and_asks_before_acting() -> None:
    """Two defaults left alone, each for a reason (05 §Tooling tiers, §Policies).

    This adapter advertises MCP, so ``auto`` reaches the ``mcp`` tier and
    the task token never enters the prompt; and these agents edit a
    directory on the operator's own machine with no container around
    them, so every tool call is asked about.
    """

    assert ClaudeAgent.tooling == "auto"
    assert ClaudeAgent.permission_policy == "ask"


def test_the_claude_prompt_is_inlined_on_the_class() -> None:
    """`AGENTS.md`: agent prompts are inlined text, never templates."""

    prompt = ImplementerAgent.system_prompt
    assert isinstance(prompt, str) and prompt.startswith("# Software engineer")
    assert "implement → wrap" in prompt
    assert "{" not in prompt and "}" not in prompt


def test_the_assignment_is_the_workflows_and_not_the_operators() -> None:
    """A check whose task varied per submission would check something else."""

    assert claude_acp.START.strip() in claude_acp.ASSIGNMENT
    assert claude_acp.GOAL in claude_acp.ASSIGNMENT
    assert claude_acp.SANDBOX_FILE in claude_acp.ASSIGNMENT


def test_each_run_starts_from_the_same_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The fixture is reset on the way in, not on the way out.

    A previous run's ``x = 2`` left in place would have the next run's
    verdict report yesterday's edit; resetting at the *end* instead would
    destroy the evidence somebody wants to look at.
    """

    monkeypatch.setenv("ATHANORE_ROOT_PATH", str(tmp_path))
    where = claude_acp.prepare()
    assert where == tmp_path / "output" / "claude-acp-sandbox"
    edited = where / claude_acp.SANDBOX_FILE
    assert edited.read_text(encoding="utf-8") == claude_acp.START

    edited.write_text("x = 2\n", encoding="utf-8")
    assert claude_acp.prepare() == where
    assert edited.read_text(encoding="utf-8") == claude_acp.START


def test_the_sandbox_is_the_servers_own_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """02 §Settings: ``root_path``, so an installed copy has somewhere to write."""

    monkeypatch.setenv("ATHANORE_ROOT_PATH", str(tmp_path))
    assert claude_acp.sandbox().parent == AthanoreSettings().root_path / "output"


async def test_the_verdict_is_the_file_and_not_the_agents_word(
    store: Store, context: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`wrap` reads `a.py` back: the check's whole answer is two strings.

    Including the case the fake produces — an agent that says it made
    the edit and wrote no file — which is exactly the failure a check
    that believed its agent would report as a pass.
    """

    monkeypatch.setenv("ATHANORE_ROOT_PATH", str(tmp_path))
    ctx: TaskContext = await context(node="wrap")
    where = claude_acp.prepare()

    with bind(ctx):
        assert await route(CLAUDE_GRAPH, "wrap", "I changed x to 2.") == []
    async with store.uow() as uow:
        written = await uow.log.list(ctx.run_id)
    assert [(entry.author, entry.kind) for entry in written] == [
        (LogAuthor.engine, LogKind.failure)
    ]
    assert "did NOT land" in written[0].text
    assert "the agent said: I changed x to 2." in written[0].text

    (where / claude_acp.SANDBOX_FILE).write_text("x = 2\n", encoding="utf-8")
    with bind(ctx):
        landed = await CLAUDE_GRAPH.nodes["wrap"].fn(said="done")
    assert landed["landed"] is True
    assert landed["content"] == "x = 2\n"
    assert "the edit landed" in landed["verdict"]
    async with store.uow() as uow:
        written = await uow.log.list(ctx.run_id)
    assert written[-1].kind == LogKind.deliverable


async def test_a_task_moved_onto_wrap_by_hand_still_reads_the_file(
    store: Store, context: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """04 §Routing edge cases: no payload is no agent, not a `TypeError`."""

    monkeypatch.setenv("ATHANORE_ROOT_PATH", str(tmp_path))
    ctx: TaskContext = await context(node="wrap")
    claude_acp.prepare()
    with bind(ctx):
        verdict = await CLAUDE_GRAPH.nodes["wrap"].fn(said=None)
    assert verdict["landed"] is False
    async with store.uow() as uow:
        written = await uow.log.list(ctx.run_id)
    assert "the agent said" not in written[0].text


def test_the_check_is_never_retried_into_a_second_opinion() -> None:
    """One turn is worth a second; a `read_text` is not (rule 3)."""

    assert CLAUDE_GRAPH.nodes["implement"].retries == 1
    assert CLAUDE_GRAPH.nodes["implement"].timeout == 600
    assert CLAUDE_GRAPH.nodes["wrap"].retries == 0


# --------------------------------------------------------------------------
# docker_acp: the same façade, dispatched into the dev stack
# --------------------------------------------------------------------------


def test_the_docker_seat_is_pi_with_three_lines_changed() -> None:
    """The only difference a container makes, as class attributes."""

    assert issubclass(DockerAgent, PiAgent)
    declared = {name for name in vars(DockerAgent) if not name.startswith("__")}
    assert declared == {"command", "model", "tooling", "permission_policy"}
    assert DockerAgent.model == docker_acp.MODEL


def test_the_command_is_the_dev_stacks_one_way_in() -> None:
    """D64, D67: `scripts/agent.sh`, not a `docker run` written here.

    Absolute rather than `AGENTS.md`'s relative form because ``command``
    is spawned in the agent's ``cwd`` and this agent's cwd is its
    sandbox — the script itself is the same one a person runs.
    """

    assert DockerAgent.command == [str(ROOT / "scripts" / "agent.sh"), "pi"]
    assert docker_acp.AGENT_SH.is_file()
    assert docker_acp.CHECKOUT == ROOT
    text = docker_acp.AGENT_SH.read_text(encoding="utf-8")
    assert "agent-pi" in text and "docker run" not in text


def test_this_example_builds_no_second_sandbox_image() -> None:
    """17 §T076's `examples/docker/` is superseded: `docker/dev` is it (D64).

    Two definitions of the sandbox is two things to keep in step, and
    the one that is already there is the one the gate, the driver and
    every other example run in.
    """

    assert not (ROOT / "examples" / "docker").exists()
    source = (ROOT / "examples" / "docker_acp" / "__init__.py").read_text(
        encoding="utf-8"
    )
    assert "docker build" not in source and "docker run" not in source
    assert (ROOT / "docker" / "dev" / "Dockerfile").is_file()


def test_the_container_is_the_guardrail() -> None:
    """05 §User-land adapters: `auto_allow`, because the sandbox is real."""

    assert DockerAgent.permission_policy == "auto_allow"
    assert ACPAgent.permission_policy == "ask"
    assert PiAgent.permission_policy == "ask"


def test_the_tier_is_http_because_the_native_ones_credentials_do_not_cross() -> None:
    """05 §Tooling tiers, D63: the extension reads two variables from its
    environment, and `docker compose run` forwards only the names a
    service lists. Neither is listed, so `native` in a sibling container
    would be an agent told about tools that cannot answer.
    """

    assert PiAgent.tooling == "native"
    assert DockerAgent.tooling == "http"

    forwarded = set()
    for entry in compose()["x-agent-environment"]:
        forwarded.add(entry.split("=", 1)[0])
    assert "ATHANORE_TASK_URL" not in forwarded
    assert "ATHANORE_TASK_TOKEN" not in forwarded


def test_the_http_tier_has_the_program_it_names() -> None:
    """The `http` tier's prompt is curl lines; the image carries curl."""

    dockerfile = (ROOT / "docker" / "dev" / "Dockerfile").read_text(encoding="utf-8")
    assert "curl" in dockerfile


def test_the_seat_still_reports_what_the_session_cost() -> None:
    """D27: pi's session file is mounted back onto the host, so it is read."""

    assert isinstance(DockerAgent.stats_provider, PiSessionStats)
    mount = "${HOST_HOME}/.pi/agent/sessions:/home/agent/.pi/agent/sessions"
    assert mount in compose()["x-volumes"]


def test_the_sandbox_is_inside_the_directory_the_container_mounts() -> None:
    """``cwd`` means the same thing on both sides, or it means nothing.

    `compose.yaml` mounts the checkout at its own host path, so a
    scratch directory anywhere else would exist for the subprocess and
    not for the session it is handed to.
    """

    assert docker_acp.sandbox() == ROOT / "output" / "docker-acp-sandbox"
    assert "${WORKSPACE}:${WORKSPACE}" in compose()["x-volumes"]
    assert compose()["x-runtime"]["network_mode"] == "host"


def test_the_scratch_project_is_a_uv_project_and_is_never_reset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The agent can `uv run` what it writes, and what it wrote stays."""

    monkeypatch.setattr(docker_acp, "CHECKOUT", tmp_path)
    where = docker_acp.prepare()
    assert where == tmp_path / "output" / "docker-acp-sandbox"
    assert "[project]" in (where / "pyproject.toml").read_text(encoding="utf-8")

    (where / "pyproject.toml").write_text("# edited\n", encoding="utf-8")
    (where / "ga.py").write_text("print(1)\n", encoding="utf-8")
    assert docker_acp.prepare() == where
    assert (where / "pyproject.toml").read_text(encoding="utf-8") == "# edited\n"
    assert (where / "ga.py").is_file()


async def test_a_wildcard_public_url_is_refused_before_an_agent_is_spawned(
    context: Any,
) -> None:
    """12 §S6: `http://0.0.0.0:4002` addresses no host from a container."""

    ctx: TaskContext = await context()
    assert docker_acp.reachable(ctx) == ctx.api_base

    for base in ("http://0.0.0.0:4002", "http://[::]:4002"):
        broken = _with_base(ctx, base)
        with pytest.raises(NonRetryable) as raised:
            docker_acp.reachable(broken)
        assert "ATHANORE_PUBLIC_URL" in str(raised.value)


def test_a_missing_dev_stack_is_a_sentence_and_not_a_transport_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A `FileNotFoundError` from a spawn says nothing an operator can act on.

    And a configured ``agent_command`` — how every example runs on
    `FakeACPAgent` — means the script is not what runs, so its absence
    means nothing (13 §Running examples on the fake).
    """

    monkeypatch.setattr(docker_acp, "AGENT_SH", tmp_path / "scripts" / "agent.sh")
    with pytest.raises(NonRetryable) as raised:
        docker_acp.dispatchable(AthanoreSettings())
    assert "dev stack" in str(raised.value)

    monkeypatch.setenv("ATHANORE_AGENT_COMMAND", "python -m athanore.testing.fake_acp")
    assert docker_acp.dispatchable(AthanoreSettings()) is None


def test_the_node_that_writes_history_is_the_one_that_is_retried() -> None:
    """One turn is worth a second: the usual failure is a bad turn (rule 3)."""

    assert DOCKER_GRAPH.nodes["implement"].retries == 1
    assert DOCKER_GRAPH.nodes["implement"].timeout == 3600


# --------------------------------------------------------------------------
# The scenarios that run both with no model in the loop
# --------------------------------------------------------------------------


def test_every_agent_node_has_a_scenario() -> None:
    """13 §Running examples on the fake: one file per **agent** node.

    `claude_acp`'s `wrap` has none and cannot have one — it is code, and
    it decides for itself, which is why a scripted run of that example
    reports "the edit did NOT land": the fake writes no files, and the
    check is about the file.
    """

    for package, graph, agents in (
        ("claude_acp", CLAUDE_GRAPH, {"implement"}),
        ("docker_acp", DOCKER_GRAPH, {"implement"}),
    ):
        directory = ROOT / "examples" / package / "scenarios"
        assert {path.name for path in directory.glob("*.json")} == {
            "default.json",
            *(f"{package}.{node}.json" for node in agents),
        }
        for node in agents:
            assert node in graph.nodes


def _with_base(ctx: TaskContext, api_base: str) -> TaskContext:
    """``ctx``, pointed at another task API URL."""

    return TaskContext(
        run_id=ctx.run_id,
        task_id=ctx.task_id,
        workflow=ctx.workflow,
        node=ctx.node,
        attempt=ctx.attempt,
        token=ctx.token,
        api_base=api_base,
        services=ctx.services,
    )
