"""The ACP session, from spawn to prompt (05 §The ACP client, T039).

The subject is :class:`~athanore.agents.acp.ACPAgent` over a **real
subprocess**: ``FakeACPAgent`` speaking ACP on stdio, scripted by a JSON
scenario. Nothing here is mocked, because every assertion is about the
wire or about the store — what the agent was sent, what it was spawned
with, and what landed in the transcript.

Four things are being pinned, and each one is a bug the MVP had:

- **Config options resolve by category.** The ids differ per agent; the
  MVP sent pi's id to claude-agent-acp and hid the rejection under a bare
  ``except`` (20 §Finding 2, D11). Here the request log is asserted
  against, and a rejection is a ``notice`` in the transcript.
- **Permission options are chosen by kind.** The fake's ``reject_first``
  is claude-agent-acp's own order, and ``options[0]`` would deny every
  tool call while reporting ``ok`` (20 §Finding 1, D10).
- **The child's environment is deliberate.** ``CLAUDE_*`` never reaches
  it, an ``env_allowlist`` keeps nothing else, and the task token and URL
  are exported (20 §Finding 4, 12 §Agents). The fake echoes what it got,
  so the assertion is over what the process actually had.
- **``settings.agent_command`` beats a subclass.** It is how every
  example runs on the fake in CI, so it has to override the class
  attribute and not merely a default (05, 13 §Running examples).

The turn loop, the outcomes and the stats are ``test_acp_outcomes.py``;
the tiers are ``test_tooling.py``.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from acp import RequestError

from athanore.agents.acp import ACPAgent, ACPClient
from athanore.engine.context import TaskContext, bind
from athanore.testing import scenario
from athanore.testing.fake_acp import ENV_MARKER

Make = Callable[..., Awaitable[TaskContext]]
Read = Callable[[TaskContext], Awaitable[list[Any]]]

#: The fake's own config advertisement, with ids that are **not** the
#: category names — pi calls the second one ``thought_level`` and
#: claude-agent-acp calls it ``effort``, which is the whole of 20
#: §Finding 2.
VENDOR_OPTIONS = [
    {"id": "the-model", "category": "model", "values": ["fast", "slow"]},
    {"id": "effort", "category": "thought_level", "values": ["low", "high"]},
]

#: An agent that advertises ids and no categories at all: the fallback 20
#: names, where the id *is* the category.
UNCATEGORISED_OPTIONS = [
    {"id": "model", "category": "model", "values": ["fast"]},
    {"id": "thought_level", "category": "thought_level", "values": ["low"]},
]


class Fake(ACPAgent):
    """A façade with nothing on it but the command the test scripts."""

    system_prompt = "You are a test agent."
    permission_policy = "auto_allow"


@pytest.fixture
def logs(tmp_path: Path) -> Path:
    """Where the fake writes the requests it received, one JSON per line."""

    return tmp_path / "requests.jsonl"


def received(path: Path) -> list[dict[str, Any]]:
    """The requests the fake logged, in order."""

    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def methods(path: Path) -> list[str]:
    return [entry["method"] for entry in received(path)]


def params_of(path: Path, method: str) -> list[dict[str, Any]]:
    return [
        entry["params"] or {} for entry in received(path) if entry["method"] == method
    ]


async def run(agent: ACPAgent, ctx: TaskContext, prompt: str = "do the work") -> Any:
    """Run ``agent`` as a node body would: bound to its task."""

    with bind(ctx):
        return await agent.run(prompt)


# --------------------------------------------------------------------------
# The handshake
# --------------------------------------------------------------------------


async def test_the_handshake_is_initialize_new_session_prompt(
    context: Make, logs: Path
) -> None:
    """05 §Session lifecycle, steps 1, 2 and 4, in order and over the wire."""

    ctx = await context()
    agent = Fake(command=scenario(text=["done"], request_log=str(logs)))
    result = await run(agent, ctx)

    assert result.ok
    assert methods(logs)[:2] == ["initialize", "session/new"]
    assert "session/prompt" in methods(logs)


async def test_initialize_carries_the_real_version(context: Make, logs: Path) -> None:
    """20 §Checked and found sound: protocol 1, and our own version."""

    from athanore import __version__

    ctx = await context()
    await run(Fake(command=scenario(request_log=str(logs))), ctx)

    initialize = params_of(logs, "initialize")[0]
    assert initialize["protocolVersion"] == 1
    assert initialize["clientInfo"] == {"name": "athanore", "version": __version__}


async def test_new_session_carries_the_agents_cwd(
    context: Make, logs: Path, tmp_path: Path
) -> None:
    """The agent's workspace is its own, and it is told which one it is."""

    ctx = await context()
    agent = Fake(command=scenario(request_log=str(logs)), cwd=str(tmp_path))
    await run(agent, ctx)

    assert params_of(logs, "session/new")[0]["cwd"] == str(tmp_path)


async def test_the_prompt_is_the_rendered_one(context: Make, logs: Path) -> None:
    """What the agent is sent is ``render_prompt``, not the bare argument."""

    ctx = await context("ship the widget")
    await run(Fake(command=scenario(request_log=str(logs))), ctx, "review the branch")

    sent = params_of(logs, "session/prompt")[0]["prompt"][0]["text"]
    assert sent.startswith("You are a test agent.")
    assert "review the branch" in sent
    assert f'Work on task {ctx.task_id} "ship the widget"' in sent
    assert ctx.token in sent  # the http tier: the token is in a header line


# --------------------------------------------------------------------------
# Config options: by category, and never silently
# --------------------------------------------------------------------------


async def test_config_ids_are_resolved_by_category(context: Make, logs: Path) -> None:
    """20 §Finding 2: the category decides, the advertised id is sent."""

    ctx = await context()
    agent = Fake(command=scenario(config_options=VENDOR_OPTIONS, request_log=str(logs)))
    agent.model = "slow"
    agent.thinking = "high"
    await run(agent, ctx)

    sent = params_of(logs, "session/set_config_option")
    assert [(one["configId"], one["value"]) for one in sent] == [
        ("the-model", "slow"),
        ("effort", "high"),
    ]


async def test_an_uncategorised_agent_falls_back_to_the_id(
    context: Make, logs: Path
) -> None:
    """20's fallback: with no categories, the id *is* the category name."""

    ctx = await context()
    agent = Fake(
        command=scenario(config_options=UNCATEGORISED_OPTIONS, request_log=str(logs))
    )
    agent.model = "fast"
    await run(agent, ctx)

    sent = params_of(logs, "session/set_config_option")
    assert [one["configId"] for one in sent] == ["model"]


async def test_nothing_is_set_when_nothing_is_configured(
    context: Make, logs: Path
) -> None:
    """A façade with no model states no opinion about the agent's."""

    ctx = await context()
    await run(Fake(command=scenario(request_log=str(logs))), ctx)

    assert params_of(logs, "session/set_config_option") == []


async def test_a_rejected_config_id_becomes_a_notice(
    context: Make, transcript: Read
) -> None:
    """D11: a rejection is logged **and** visible in the transcript.

    The MVP logged and continued on the agent's default model, which is
    how a whole build runs on the wrong one without anyone noticing.
    """

    ctx = await context()
    agent = Fake(
        command=scenario(
            config_options=VENDOR_OPTIONS, reject_config=["the-model"], text=["done"]
        )
    )
    agent.model = "slow"
    result = await run(agent, ctx)

    assert result.ok, "a rejected option does not fail the run"
    notices = [text for kind, text in await transcript(ctx) if kind == "notice"]
    assert len(notices) == 1
    assert "model could not be set to 'slow'" in notices[0]
    assert "own default" in notices[0]


async def test_a_category_the_agent_does_not_have_becomes_a_notice(
    context: Make, transcript: Read
) -> None:
    """Nothing to set is as invisible as a rejection, and as loud."""

    ctx = await context()
    agent = Fake(
        command=scenario(
            config_options=[{"id": "mode", "category": "mode", "values": ["auto"]}]
        )
    )
    agent.thinking = "high"
    await run(agent, ctx)

    notices = [text for kind, text in await transcript(ctx) if kind == "notice"]
    assert notices == [
        "thought_level could not be set to 'high': the agent advertises no "
        "thought_level option. The agent is answering on its own default."
    ]


# --------------------------------------------------------------------------
# The transcript
# --------------------------------------------------------------------------


async def test_text_and_thought_chunks_land_with_the_right_kinds(
    context: Make, transcript: Read
) -> None:
    """05 §The ACP client: the mapping, over the wire and into the rows."""

    ctx = await context()
    agent = Fake(
        command=scenario(text=["first ", "second"], thoughts=["hmm"], tool_calls=1)
    )
    result = await run(agent, ctx)

    assert await transcript(ctx) == [
        ("thought", "hmm"),
        ("text", "first "),
        ("text", "second"),
        ("tool_call", "fake tool 1"),
        ("tool_result", "completed"),
    ]
    assert result.text == "first second", "AgentResult.text is the assistant text"


async def test_tool_calls_are_counted_for_the_stats_entry(
    context: Make, stats_lines: Read
) -> None:
    """05 §Stats entry: ``tool_calls`` is the ``ToolCallStart`` count."""

    ctx = await context()
    result = await run(Fake(command=scenario(tool_calls=3)), ctx)

    assert result.stats["tool_calls"] == 3
    assert "tools=3 calls" in (await stats_lines(ctx))[0]


async def test_a_run_with_no_tool_calls_records_zero(context: Make) -> None:
    """A measured zero is data; it is the *unknown* that is omitted."""

    ctx = await context()
    result = await run(Fake(command=scenario(text=["done"])), ctx)

    assert result.stats["tool_calls"] == 0


# --------------------------------------------------------------------------
# The environment the child is spawned with
# --------------------------------------------------------------------------


def echoed(chunks: list[tuple[str, str]]) -> dict[str, str]:
    """The environment the fake reported, as a dict (13 §Fakes)."""

    listing = next(
        text for kind, text in chunks if kind == "text" and text.startswith(ENV_MARKER)
    )
    return dict(line.split("=", 1) for line in listing.splitlines()[1:] if "=" in line)


async def test_session_scoped_variables_are_scrubbed(
    context: Make, transcript: Read, monkeypatch: pytest.MonkeyPatch
) -> None:
    """20 §Finding 4: a child never inherits another agent's session."""

    monkeypatch.setenv("CLAUDE_CODE_MESSAGING_TOKEN", "secret")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_PID", "42")
    monkeypatch.setenv("PATH_LIKE_THING", "kept")

    ctx = await context()
    await run(Fake(command=scenario(env_echo=True)), ctx)

    env = echoed(await transcript(ctx))
    assert "CLAUDE_CODE_MESSAGING_TOKEN" not in env
    assert "CLAUDECODE" not in env
    assert "CLAUDE_PID" not in env
    assert env["PATH_LIKE_THING"] == "kept"


async def test_the_task_url_and_token_are_exported(
    context: Make, transcript: Read
) -> None:
    """19 §Environment: an adapter that can read env need not read the prompt."""

    ctx = await context()
    await run(Fake(command=scenario(env_echo=True)), ctx)

    env = echoed(await transcript(ctx))
    assert env["ATHANORE_TASK_TOKEN"] == ctx.token
    assert env["ATHANORE_TASK_URL"] == (f"{ctx.api_base}/api/agent/tasks/{ctx.task_id}")


async def test_an_allowlist_keeps_nothing_else(
    context: Make, transcript: Read, monkeypatch: pytest.MonkeyPatch
) -> None:
    """12 §Agents: ``env_allowlist`` is allow-nothing-by-default."""

    monkeypatch.setenv("KEEP_ME", "yes")
    monkeypatch.setenv("DROP_ME", "no")

    ctx = await context()
    agent = Fake(command=scenario(env_echo=True))
    agent.env_allowlist = ["KEEP_ME", "PATH", "HOME", "LANG"]
    await run(agent, ctx)

    env = echoed(await transcript(ctx))
    assert env["KEEP_ME"] == "yes"
    assert "DROP_ME" not in env
    assert env["ATHANORE_TASK_TOKEN"] == ctx.token, "the task is never allowlisted away"


async def test_explicit_env_is_merged_last(
    context: Make, transcript: Read, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one thing an author stated by hand wins over the scrub."""

    monkeypatch.setenv("OVERRIDDEN", "from the parent")

    ctx = await context()
    agent = Fake(
        command=scenario(env_echo=True),
        env={"OVERRIDDEN": "from the class", "CLAUDE_KEPT": "stated on purpose"},
    )
    await run(agent, ctx)

    env = echoed(await transcript(ctx))
    assert env["OVERRIDDEN"] == "from the class"
    assert env["CLAUDE_KEPT"] == "stated on purpose"


# --------------------------------------------------------------------------
# `settings.agent_command`
# --------------------------------------------------------------------------


async def test_agent_command_replaces_a_subclasss_command(
    context: Make, logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """05: it overrides **every** ``ACPAgent``, whatever the subclass set.

    This is how the examples run on the fake in CI, so a version that
    only replaced an unset default would silently spawn ``npx pi-acp`` in
    a container with no network.
    """

    class Vendor(Fake):
        command = ["definitely-not-a-real-agent", "--acp"]

    monkeypatch.setenv(
        "ATHANORE_AGENT_COMMAND",
        json.dumps(scenario(text=["from the fake"], request_log=str(logs))),
    )
    ctx = await context()
    result = await run(Vendor(), ctx)

    assert result.text == "from the fake"
    assert methods(logs)[0] == "initialize"


async def test_agent_command_may_be_a_shell_string(
    context: Make, logs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """05: "a JSON list or a shell-split string"."""

    argv = scenario(text=["shell"], request_log=str(logs))
    monkeypatch.setenv("ATHANORE_AGENT_COMMAND", " ".join(argv))
    ctx = await context()

    assert (await run(Fake(command=["nope"]), ctx)).text == "shell"


# --------------------------------------------------------------------------
# Permissions over the wire
# --------------------------------------------------------------------------


async def test_reject_first_options_still_pick_allow_once(
    context: Make, tmp_path: Path
) -> None:
    """20 §Finding 1, end to end: ``options[0]`` would deny every call.

    The fake's ``reject_first`` is claude-agent-acp's own list, rejection
    first. The answer that comes back is asserted from the fake's side —
    what the agent was actually told — not from the policy's return value.
    """

    responses = tmp_path / "responses.jsonl"
    ctx = await context()
    agent = Fake(
        command=scenario(permissions=["reject_first"], response_log=str(responses))
    )
    result = await run(agent, ctx)

    answered = [json.loads(line) for line in responses.read_text().splitlines()]
    assert answered[0]["result"]["outcome"] == {
        "outcome": "selected",
        "optionId": "allow",
    }
    assert "denied_permissions" not in result.stats, "an allow is not a denial"


async def test_denied_permissions_are_counted(context: Make) -> None:
    """05 §Stats entry: a run whose agent was refused everything shows it."""

    ctx = await context()
    agent = Fake(command=scenario(permissions=["reject_first", "reject_first"]))
    agent.permission_policy = "auto_deny"
    result = await run(agent, ctx)

    assert result.stats["denied_permissions"] == 2


# --------------------------------------------------------------------------
# What this client refuses to do
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("call", "method"),
    [
        ("write_text_file", "fs/write_text_file"),
        ("read_text_file", "fs/read_text_file"),
        ("create_terminal", "terminal/create"),
        ("terminal_output", "terminal/output"),
        ("release_terminal", "terminal/release"),
        ("wait_for_terminal_exit", "terminal/wait_for_exit"),
        ("kill_terminal", "terminal/kill"),
    ],
)
async def test_fs_and_terminal_answer_method_not_found(call: str, method: str) -> None:
    """05, 20 §Checked and found sound: agents do their own I/O.

    Asserted on the client directly. The alternative would be an agent
    that calls them, and the point is that no agent gets an answer — a
    protocol base class whose stubs returned ``None`` would answer
    ``null``, which reads to an adapter as "it worked".
    """

    client = ACPClient(Fake(command=["unused"]), None)
    with pytest.raises(RequestError) as raised:
        await getattr(client, call)(
            session_id="s", path="/tmp/x", content="", terminal_id="t", command="ls"
        )

    assert raised.value.code == -32601
    assert raised.value.data == {"method": method}


async def test_an_unknown_extension_method_is_not_found() -> None:
    """The open end of the protocol is open, not silently accepted."""

    client = ACPClient(Fake(command=["unused"]), None)
    with pytest.raises(RequestError):
        await client.ext_method("something", {})


async def test_complete_elicitation_is_a_no_op() -> None:
    """05 §Policies: accepted and ignored. There is nothing to take down."""

    client = ACPClient(Fake(command=["unused"]), None)

    assert await client.complete_elicitation("elicit_0") is None
