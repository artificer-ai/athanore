"""The ACP session, from spawn to prompt (05 §The ACP client, T039).

The subject is :class:`~athanore.agents.acp.ACPAgent` over a **real
subprocess**: ``FakeACPAgent`` speaking ACP on stdio, scripted by a JSON
scenario. Nothing here is mocked, because every assertion is about the
wire or about the store — what the agent was sent, what it was spawned
with, and what landed in the transcript.

Six things are being pinned, and four of them are bugs the MVP had:

- **Config options resolve by category.** The ids differ per agent; the
  MVP sent pi's id to claude-agent-acp and hid the rejection under a bare
  ``except`` (20 §Finding 2, D11). Here the request log is asserted
  against, and a rejection is a ``notice`` in the transcript.
- **Permission options are chosen by kind.** The fake's ``reject_first``
  is claude-agent-acp's own order, and ``options[0]`` would deny every
  tool call while reporting ``ok`` (20 §Finding 1, D10).
- **The child's environment is deliberate.** ``CLAUDE_*`` never reaches
  it, an ``env_allowlist`` keeps nothing else, and the task token and URL
  are exported — except on the ``none`` tier, which is given neither
  (D271) (20 §Finding 4, 12 §Agents). The fake echoes what it got, so
  the assertion is over what the process actually had.
- **``settings.agent_command`` beats a subclass.** It is how every
  example runs on the fake in CI, so it has to override the class
  attribute and not merely a default (05, 13 §Running examples).
- **A continued run joins the session it was given, or raises.** With
  ``session_id=`` the façade re-opens that session by ``session/resume``
  or ``session/load`` and never a ``session/new``; the replay a load
  produces is not this attempt's transcript and counts nothing (23
  §Lifecycle of a continued run, §Refusal, D254, D255).
- **A session held open is one process and one entry per prompt.**
  ``open()`` spawns once and yields a session a body prompts as often as
  it likes; each prompt records its own stats entry, the exit records
  none and stops the child on every path, and a dead session refuses
  every later prompt (23 §A session held open, D264).

The turn loop, the outcomes and the stats are ``test_acp_outcomes.py``;
the tiers are ``test_tooling.py`` — all but ``none``, which is here
because that file's façade declares an ``output_model`` and a ``none``
class may not (05 §Tooling tiers, D271).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
import structlog
from acp import RequestError
from acp.schema import (
    AgentMessageChunk,
    PermissionOption,
    TextContentBlock,
    ToolCallStart,
    ToolCallUpdate,
)
from pydantic import BaseModel

from athanore.agents.acp import ACPAgent, ACPClient, AgentSession
from athanore.agents.base import AgentError
from athanore.agents.policies import MCP_SERVER_NAME
from athanore.engine.context import TaskContext, bind
from athanore.testing import FakeStatsProvider, scenario
from athanore.testing.fake_acp import ENV_MARKER

Make = Callable[..., Awaitable[TaskContext]]
Read = Callable[[TaskContext], Awaitable[list[Any]]]

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 10.0

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
# Continuing a session (23)
# --------------------------------------------------------------------------


class Spy(Fake):
    """A ``Fake`` that keeps the child, so a test can assert it is gone.

    The same ten lines as ``test_acp_outcomes.py``'s: the subprocess is
    private to one ``run()``, and looking over the façade's shoulder as
    it spawns is the only honest way to assert ``returncode`` was set.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.process: asyncio.subprocess.Process | None = None

    async def _spawn(self, session: Any, settings: Any, ctx: Any) -> None:
        await super()._spawn(session, settings, ctx)
        self.process = session.process


class Recording(FakeStatsProvider):
    """A provider that says *which* method was called, not only that one was.

    ``FakeStatsProvider.calls`` records ``(session_id, cwd)`` for both
    methods alike, and the assertion of 23 §Stats is the distinction:
    ``final_stop_reason`` on every run, ``stats`` on a fresh one only.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.called: list[tuple[str, str]] = []

    async def stats(self, session_id: str, cwd: str | None) -> Any:
        self.called.append(("stats", session_id))
        return await super().stats(session_id, cwd)

    async def final_stop_reason(self, session_id: str, cwd: str | None) -> Any:
        self.called.append(("final_stop_reason", session_id))
        return await super().final_stop_reason(session_id, cwd)


@pytest.fixture
def sessions(tmp_path: Path) -> dict[str, Any]:
    """The fake's ``sessions`` key: a directory the session file lives in."""

    return {"dir": str(tmp_path / "sessions")}


def session_file(sessions: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    """The updates the fake recorded for one session, in order (13 §Fakes)."""

    return json.loads((Path(sessions["dir"]) / f"{session_id}.json").read_text())


async def first_run(
    context: Make, sessions: dict[str, Any], cwd: str, **keys: Any
) -> tuple[TaskContext, Any]:
    """A fresh run on a session the fake persists, and the context it ran in."""

    ctx = await context()
    agent = Fake(command=scenario(sessions=sessions, **keys), cwd=cwd)
    return ctx, await run(agent, ctx)


async def test_a_continued_run_loads_the_session_and_opens_no_new_one(
    context: Make,
    transcript: Read,
    logs: Path,
    sessions: dict[str, Any],
    tmp_path: Path,
) -> None:
    """23 §Lifecycle of a continued run, the ``load`` path, over the wire.

    The transcript assertion is exact: a replayed ``one`` or a replayed
    tool call anywhere in it is the bug D255 exists to keep out, and the
    fake re-sends the whole file before it answers the load.
    """

    cwd = str(tmp_path)
    ctx1, first = await first_run(context, sessions, cwd, text=["one"], tool_calls=1)
    before = session_file(sessions, first.session_id)

    ctx2 = await context()
    agent = Fake(
        command=scenario(
            sessions=sessions, text=["two"], tool_calls=2, request_log=str(logs)
        ),
        cwd=cwd,
        session_id=first.session_id,
    )
    again = await run(agent, ctx2)

    assert methods(logs)[:2] == ["initialize", "session/load"]
    assert "session/new" not in methods(logs)
    assert "session/prompt" in methods(logs)
    load = params_of(logs, "session/load")[0]
    assert load["sessionId"] == first.session_id
    assert load["cwd"] == cwd
    assert load["mcpServers"] == []

    assert again.ok
    assert again.session_id == first.session_id
    assert again.stats["session_id"] == first.session_id
    assert again.text == "two", "none of the first run's text"
    assert again.stats["tool_calls"] == 2, "the second turn's, not both turns'"
    assert await transcript(ctx2) == [
        ("notice", f"continuing session {first.session_id}"),
        ("text", "two"),
        ("tool_call", "fake tool 1"),
        ("tool_result", "completed"),
        ("tool_call", "fake tool 2"),
        ("tool_result", "completed"),
    ]
    assert await transcript(ctx1) == [
        ("text", "one"),
        ("tool_call", "fake tool 1"),
        ("tool_result", "completed"),
    ], "the first attempt's transcript is untouched"

    after = session_file(sessions, first.session_id)
    assert after[: len(before)] == before, "the load carried on in the same file"
    assert len(after) > len(before), "and the second turn was appended to it"


async def test_the_discarded_replay_is_logged_once_at_debug(
    context: Make, sessions: dict[str, Any], tmp_path: Path
) -> None:
    """23 §The replay: the count is the file's length, so a short transcript
    has a line saying why."""

    cwd = str(tmp_path)
    _ctx1, first = await first_run(context, sessions, cwd, text=["one"], tool_calls=1)
    replayed = len(session_file(sessions, first.session_id))
    assert replayed > 0

    ctx2 = await context()
    agent = Fake(
        command=scenario(sessions=sessions, text=["two"]),
        cwd=cwd,
        session_id=first.session_id,
    )
    with structlog.testing.capture_logs() as captured:
        await run(agent, ctx2)

    lines = [entry for entry in captured if entry["event"] == "replay discarded"]
    assert len(lines) == 1
    assert lines[0]["log_level"] == "debug"
    assert lines[0]["session_id"] == first.session_id
    assert lines[0]["count"] == replayed


async def test_a_continued_run_resumes_when_the_agent_can(
    context: Make,
    transcript: Read,
    logs: Path,
    sessions: dict[str, Any],
    tmp_path: Path,
) -> None:
    """D255: ``session/resume`` when advertised — cheaper, and nothing to drop."""

    cwd = str(tmp_path)
    resumable = {**sessions, "resume": True}
    _ctx1, first = await first_run(context, resumable, cwd, text=["one"])

    ctx2 = await context()
    agent = Fake(
        command=scenario(sessions=resumable, text=["two"], request_log=str(logs)),
        cwd=cwd,
        session_id=first.session_id,
    )
    with structlog.testing.capture_logs() as captured:
        again = await run(agent, ctx2)

    assert "session/resume" in methods(logs)
    assert "session/load" not in methods(logs)
    assert "session/new" not in methods(logs)
    resume = params_of(logs, "session/resume")[0]
    assert resume["sessionId"] == first.session_id
    assert resume["cwd"] == cwd
    assert resume["mcpServers"] == []
    assert again.session_id == first.session_id
    assert await transcript(ctx2) == [
        ("notice", f"continuing session {first.session_id}"),
        ("text", "two"),
    ]
    assert not [e for e in captured if e["event"] == "replay discarded"]


async def test_config_options_are_set_on_the_continued_session(
    context: Make, logs: Path, sessions: dict[str, Any], tmp_path: Path
) -> None:
    """23 §Lifecycle step 2: a continued session is re-told the class's choices."""

    cwd = str(tmp_path)
    _ctx1, first = await first_run(context, sessions, cwd)

    ctx2 = await context()
    agent = Fake(
        command=scenario(
            sessions=sessions, config_options=VENDOR_OPTIONS, request_log=str(logs)
        ),
        cwd=cwd,
        session_id=first.session_id,
    )
    agent.model = "slow"
    agent.thinking = "high"
    await run(agent, ctx2)

    sent = params_of(logs, "session/set_config_option")
    assert methods(logs).index("session/load") < methods(logs).index(
        "session/set_config_option"
    )
    assert [(one["configId"], one["value"]) for one in sent] == [
        ("the-model", "slow"),
        ("effort", "high"),
    ]
    assert {one["sessionId"] for one in sent} == {first.session_id}


async def test_the_continuing_notice_comes_before_a_rejected_option(
    context: Make, transcript: Read, sessions: dict[str, Any], tmp_path: Path
) -> None:
    """23 §Lifecycle step 3: the attempt's transcript *opens* with the notice."""

    cwd = str(tmp_path)
    _ctx1, first = await first_run(context, sessions, cwd)

    ctx2 = await context()
    agent = Fake(
        command=scenario(
            sessions=sessions,
            config_options=VENDOR_OPTIONS,
            reject_config=["the-model"],
            text=["two"],
        ),
        cwd=cwd,
        session_id=first.session_id,
    )
    agent.model = "slow"
    result = await run(agent, ctx2)

    assert result.ok
    chunks = await transcript(ctx2)
    assert chunks[0] == ("notice", f"continuing session {first.session_id}")
    assert chunks[1][0] == "notice"
    assert "model could not be set to 'slow'" in chunks[1][1]
    assert chunks[2] == ("text", "two")


async def test_the_mcp_tier_hands_this_tasks_server_to_the_load(
    context: Make, logs: Path, sessions: dict[str, Any], tmp_path: Path
) -> None:
    """23 §Lifecycle step 1: a continued session is not a continued token.

    Run 1 did not advertise MCP; run 2 does, and the server on its load
    carries the *second* task's token, in the shape ``test_tooling.py``
    asserts for ``session/new``.
    """

    cwd = str(tmp_path)
    _ctx1, first = await first_run(context, sessions, cwd)

    ctx2 = await context()
    agent = Fake(
        command=scenario(sessions=sessions, advertise_mcp=True, request_log=str(logs)),
        cwd=cwd,
        session_id=first.session_id,
    )
    await run(agent, ctx2)

    load = params_of(logs, "session/load")[0]
    assert load["mcpServers"] == [
        {
            "type": "http",
            "name": MCP_SERVER_NAME,
            "url": f"{ctx2.api_base}/mcp/agent",
            "headers": [{"name": "X-Athanore-Token", "value": ctx2.token}],
        }
    ]


async def test_an_agent_that_can_do_neither_is_refused_before_any_prompt(
    context: Make, stats_lines: Read, logs: Path
) -> None:
    """23 §Refusal, first case: after ``initialize``, before any prompt.

    No ``sessions`` key, so the fake advertises neither method. The child
    is stopped, one ``failed/transport`` entry is recorded, and it names
    no session because none was joined.
    """

    ctx = await context()
    agent = Spy(
        command=scenario(text=["never"], request_log=str(logs)),
        session_id="01a0-anything",
    )
    with pytest.raises(
        AgentError,
        match=(
            r"Spy cannot continue a session: the agent advertises neither "
            r"session/resume nor session/load"
        ),
    ):
        await run(agent, ctx)

    assert methods(logs) == ["initialize"]
    assert agent.process is not None and agent.process.returncode is not None
    lines = await stats_lines(ctx)
    assert len(lines) == 1
    assert "failed (transport)" in lines[0]
    assert "session=" not in lines[0]


@pytest.mark.parametrize(
    ("resume", "method"),
    [(False, "session/load"), (True, "session/resume")],
)
async def test_an_unknown_session_quotes_the_agents_error(
    context: Make,
    stats_lines: Read,
    logs: Path,
    sessions: dict[str, Any],
    resume: bool,
    method: str,
) -> None:
    """23 §Refusal, second case: the agent's JSON-RPC error, quoted, no fallback."""

    ctx = await context()
    agent = Spy(
        command=scenario(
            sessions={**sessions, "resume": resume}, request_log=str(logs)
        ),
        session_id="nope",
    )
    with pytest.raises(
        AgentError,
        match=r"the agent could not continue session nope: no such session: nope",
    ):
        await run(agent, ctx)

    assert methods(logs) == ["initialize", method]
    assert agent.process is not None and agent.process.returncode is not None
    lines = await stats_lines(ctx)
    assert len(lines) == 1
    assert "failed (transport)" in lines[0]
    assert "session=" not in lines[0]


async def test_the_provider_is_asked_for_a_stop_reason_but_not_for_stats(
    context: Make, sessions: dict[str, Any], tmp_path: Path
) -> None:
    """23 §Stats, D256: a provider reports a session; a continued run is a
    fraction of one. Tokens are ACP's, the model is the class's."""

    cwd = str(tmp_path)
    ctx1 = await context()
    fresh = Fake(command=scenario(sessions=sessions), cwd=cwd)
    fresh.stats_provider = Recording(
        stats={"cost": 0.25, "input_tokens": 999, "model": "answered-with"},
        stop_reason=None,
    )
    first = await run(fresh, ctx1)
    sid = first.session_id

    assert first.stats["cost"] == 0.25
    assert first.stats["model"] == "answered-with"
    assert fresh.stats_provider.called == [("final_stop_reason", sid), ("stats", sid)]

    ctx2 = await context()
    agent = Fake(
        command=scenario(sessions=sessions, usage={"input": 10, "output": 2}),
        cwd=cwd,
        session_id=sid,
    )
    agent.model = "asked-for"
    provider = Recording(
        stats={"cost": 0.25, "input_tokens": 999, "model": "answered-with"},
        stop_reason=None,
    )
    agent.stats_provider = provider
    again = await run(agent, ctx2)

    assert provider.called == [("final_stop_reason", sid)]
    assert "cost" not in again.stats
    assert again.stats["input_tokens"] == 10
    assert again.stats["output_tokens"] == 2
    assert again.stats["model"] == "asked-for"
    assert again.stats["session_id"] == sid


async def test_truncation_is_still_the_providers_call_on_a_continued_run(
    context: Make, sessions: dict[str, Any], tmp_path: Path
) -> None:
    """23 §Stats: ``final_stop_reason`` decides truncation on both paths."""

    cwd = str(tmp_path)
    _ctx1, first = await first_run(context, sessions, cwd)

    ctx2 = await context()
    agent = Fake(
        command=scenario(sessions=sessions), cwd=cwd, session_id=first.session_id
    )
    agent.stats_provider = Recording(stop_reason="length")
    again = await run(agent, ctx2)

    assert not again.ok
    assert again.error == "truncated"


async def test_a_replaying_client_answers_requests_and_drops_updates() -> None:
    """23 §The replay, on the client directly: updates are dropped and
    counted, a permission is still answered, and the flag is not sticky."""

    client = ACPClient(Fake(command=["unused"]), None)
    client.replaying = True

    await client.session_update(
        "s",
        AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="old news"),
        ),
    )
    await client.session_update(
        "s", ToolCallStart(session_update="tool_call", tool_call_id="c1", title="ls")
    )
    assert client.text == []
    assert client.tool_calls == 0
    assert client.replayed == 2

    answer = await client.request_permission(
        "s",
        ToolCallUpdate(tool_call_id="c1", title="ls"),
        [
            PermissionOption(option_id="reject", name="Deny", kind="reject_once"),
            PermissionOption(option_id="allow", name="Allow", kind="allow_once"),
        ],
    )
    assert answer.outcome.option_id == "allow", "the policy answered under the flag"

    client.replaying = False
    await client.session_update(
        "s",
        AgentMessageChunk(
            session_update="agent_message_chunk",
            content=TextContentBlock(type="text", text="live"),
        ),
    )
    assert client.text == ["live"]
    assert client.replayed == 2


# --------------------------------------------------------------------------
# Holding a session (23)
# --------------------------------------------------------------------------


class Verdict(BaseModel):
    """The shape the missing-submission test asks for."""

    verdict: str


class Judged(Spy):
    """A ``Spy`` that wants a submission and never asks twice for it."""

    output_model = Verdict
    max_repair_turns = 0


async def hold(agent: ACPAgent, ctx: TaskContext, *prompts: str) -> list[Any]:
    """Open ``agent`` once, prompt it with each text in order, close it."""

    with bind(ctx):
        async with agent.open() as held:
            return [await held.prompt(text) for text in prompts]


def stopped(agent: Spy) -> bool:
    """Whether the child the spy kept has been reaped."""

    return agent.process is not None and agent.process.returncode is not None


async def test_two_prompts_share_one_process_and_one_session(
    context: Make, transcript: Read, stats_lines: Read, logs: Path
) -> None:
    """23 §Lifecycle of a held session: one spawn, one ``session/new``, two
    ``session/prompt``; the child alive between the prompts and gone after
    the block; each result and each entry the prompt's own."""

    ctx = await context()
    agent = Spy(
        command=scenario(
            prompts=[
                {"text": ["one"], "tool_calls": 1},
                {"text": ["two"], "tool_calls": 2, "sleep_s": 2},
            ],
            request_log=str(logs),
        )
    )
    with bind(ctx):
        async with agent.open() as held:
            assert isinstance(held, AgentSession)
            sid = held.session_id
            first = await held.prompt("say one")
            assert agent.process is not None
            assert agent.process.returncode is None, "alive between the prompts"
            second = await held.prompt("say two")
    assert stopped(agent), "and stopped by the exit"

    assert methods(logs).count("initialize") == 1
    assert methods(logs).count("session/new") == 1
    assert methods(logs).count("session/prompt") == 2
    for sent in params_of(logs, "session/prompt"):
        text = sent["prompt"][0]["text"]
        assert text.startswith("You are a test agent."), "the full assembly, each time"
        assert f"Work on task {ctx.task_id}" in text

    assert first.ok and second.ok
    assert first.text == "one"
    assert second.text == "two", "the second prompt's text, not both prompts'"
    assert first.session_id == second.session_id == sid
    assert await transcript(ctx) == [
        ("text", "one"),
        ("tool_call", "fake tool 1"),
        ("tool_result", "completed"),
        ("text", "two"),
        ("tool_call", "fake tool 1"),
        ("tool_result", "completed"),
        ("tool_call", "fake tool 2"),
        ("tool_result", "completed"),
    ]

    lines = await stats_lines(ctx)
    assert len(lines) == 2, "one entry per prompt, none at exit"
    assert all(f"session={sid[:8]}" in line for line in lines)
    assert first.stats["session_id"] == second.stats["session_id"] == sid
    assert first.stats["tool_calls"] == 1
    assert second.stats["tool_calls"] == 2, "the prompt's own, not the session's"
    assert first.stats["duration_s"] <= 1
    assert second.stats["duration_s"] >= 2, "the prompt's own, from its send"


async def test_run_is_open_plus_one_prompt(
    context: Make, stats_lines: Read, logs: Path
) -> None:
    """23 §Surface: the one-shot form is the held form with one prompt.

    Every other lifecycle and outcomes test is the rest of this assertion;
    this one says the wire, the child and the entry count are unchanged.
    """

    ctx = await context()
    agent = Spy(command=scenario(text=["done"], tool_calls=1, request_log=str(logs)))
    result = await run(agent, ctx)

    assert methods(logs).count("session/new") == 1
    assert methods(logs).count("session/prompt") == 1
    assert stopped(agent)
    assert result.ok and result.text == "done"
    assert result.stats["tool_calls"] == 1
    assert len(await stats_lines(ctx)) == 1


async def test_an_exception_in_the_block_stops_the_child_and_records_nothing_more(
    context: Make, stats_lines: Read
) -> None:
    """23 step 5: the exit is a ``finally`` and records no entry of its own —
    the prompt's is the only one, and a block that asked nothing has none."""

    ctx = await context()
    agent = Spy(command=scenario(prompts=[{"text": ["one"]}]))
    with pytest.raises(RuntimeError, match="body"):
        with bind(ctx):
            async with agent.open() as held:
                await held.prompt("say one")
                raise RuntimeError("body")
    assert stopped(agent)
    lines = await stats_lines(ctx)
    assert len(lines) == 1, "the prompt's entry, and nothing at exit"
    assert " ok " in lines[0]

    ctx2 = await context()
    quiet = Spy(command=scenario(prompts=[{"text": ["one"]}]))
    with pytest.raises(RuntimeError, match="at once"):
        with bind(ctx2):
            async with quiet.open():
                raise RuntimeError("at once")
    assert stopped(quiet)
    assert await stats_lines(ctx2) == [], "nothing was asked, nothing is recorded"


async def test_a_cancelled_prompt_records_shutdown_and_the_exit_stops_the_child(
    context: Make, stats_lines: Read
) -> None:
    """23 step 5, D266: a prompt in flight when the body is cancelled records
    ``failed/shutdown`` as any cancelled run does, then the exit stops the
    child."""

    ctx = await context()
    agent = Spy(command=scenario(prompts=[{"text": ["one"]}, {"sleep_s": 30}]))
    parked = asyncio.Event()

    async def body() -> None:
        with bind(ctx):
            async with agent.open() as held:
                await held.prompt("say one")
                parked.set()
                await held.prompt("take forever")

    task = asyncio.get_running_loop().create_task(body())
    async with asyncio.timeout(DEADLINE):
        await parked.wait()
        await asyncio.sleep(0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert stopped(agent), "no zombie"
    lines = await stats_lines(ctx)
    assert len(lines) == 2, "the cancelled prompt pays its bill once, not twice"
    assert " ok " in lines[0]
    assert "failed (shutdown)" in lines[1]


async def test_a_timeout_closes_the_session_and_the_next_prompt_is_refused(
    context: Make, stats_lines: Read, logs: Path
) -> None:
    """23 step 4: after a timeout the child is stopped **at once** — inside
    the block — and every later prompt raises ``the session is closed``."""

    ctx = await context()
    agent = Spy(
        command=scenario(
            prompts=[{"sleep_s": 30}, {"text": ["never"]}], request_log=str(logs)
        )
    )
    agent.timeout = 0.5
    with bind(ctx):
        async with agent.open() as held:
            with pytest.raises(AgentError, match="did not finish"):
                await held.prompt("take forever")
            assert stopped(agent), "stopped inside the block, not at its exit"
            with pytest.raises(
                AgentError,
                match=r"the session is closed: the agent did not finish within 0\.5s",
            ):
                await held.prompt("anything")

    assert methods(logs).count("session/prompt") == 1, "the refusal sent nothing"
    lines = await stats_lines(ctx)
    assert len(lines) == 1, "the refused prompt records no entry"
    assert "failed (timeout)" in lines[0]


async def test_a_transport_failure_closes_the_session_and_the_next_prompt_is_refused(
    context: Make, stats_lines: Read, logs: Path
) -> None:
    """23 step 4, the other reason that kills a session: a policy that
    could not be honoured is the transport failure D10 makes loud."""

    ctx = await context()
    agent = Spy(
        command=scenario(
            prompts=[
                {"permissions": [{"options": [{"kind": "reject_once"}]}]},
                {"text": ["never"]},
            ],
            request_log=str(logs),
        )
    )
    with bind(ctx):
        async with agent.open() as held:
            with pytest.raises(AgentError, match="auto_allow"):
                await held.prompt("do a thing")
            assert stopped(agent)
            with pytest.raises(AgentError, match="the session is closed: .*auto_allow"):
                await held.prompt("anything")

    assert methods(logs).count("session/prompt") == 1
    lines = await stats_lines(ctx)
    assert len(lines) == 1
    assert "failed (transport)" in lines[0]


@pytest.mark.parametrize("stop", ["refusal", "cancelled"])
async def test_a_refusal_leaves_the_session_open(
    context: Make, stats_lines: Read, logs: Path, stop: str
) -> None:
    """23 step 4: a failed *result* is an answer; the process is fine and the
    next prompt is answered on the same session."""

    ctx = await context()
    agent = Fake(
        command=scenario(
            prompts=[{"stop_reason": stop}, {"text": ["two"]}], request_log=str(logs)
        )
    )
    first, second = await hold(agent, ctx, "one", "two")

    assert first.ok is False
    assert first.error == stop
    assert second.ok
    assert second.text == "two"
    assert first.session_id == second.session_id
    assert methods(logs).count("session/prompt") == 2
    lines = await stats_lines(ctx)
    assert len(lines) == 2
    assert f"failed ({stop})" in lines[0]
    assert " ok " in lines[1]


async def test_a_missing_submission_leaves_the_session_open(
    served_context: Make, stats_lines: Read
) -> None:
    """D266: ``no_submission`` raises, as from ``run()``, and closes nothing —
    the second prompt submits and the body gets its value."""

    ctx = await served_context()
    agent = Judged(command=scenario(prompts=[{}, {"submit": {"verdict": "ok"}}]))
    with bind(ctx):
        async with agent.open() as held:
            with pytest.raises(AgentError, match="without a valid submission"):
                await held.prompt("submit something")
            assert not stopped(agent), "the process is fine"
            second = await held.prompt("try again")
    assert second.ok
    assert second.output.verdict == "ok"
    lines = await stats_lines(ctx)
    assert len(lines) == 2
    assert "failed (no_submission)" in lines[0]
    assert " ok " in lines[1]


async def test_a_second_prompt_while_one_is_in_flight_is_a_runtime_error(
    context: Make, stats_lines: Read, logs: Path
) -> None:
    """23: one prompt at a time; the second is refused before the wire."""

    ctx = await context()
    agent = Fake(
        command=scenario(
            prompts=[{"text": ["one"], "sleep_s": 1}], request_log=str(logs)
        )
    )
    with bind(ctx):
        async with agent.open() as held:
            async with asyncio.timeout(DEADLINE):
                first = asyncio.get_running_loop().create_task(held.prompt("a"))
                await asyncio.sleep(0.1)
                with pytest.raises(RuntimeError, match="already in flight"):
                    await held.prompt("b")
                result = await first
    assert result.ok and result.text == "one"
    assert methods(logs).count("session/prompt") == 1
    assert len(await stats_lines(ctx)) == 1, "the refused prompt records nothing"


@pytest.mark.parametrize(
    ("resume", "method"),
    [(False, "session/load"), (True, "session/resume")],
)
async def test_open_with_a_session_id_continues_it_once_then_prompts(
    context: Make,
    transcript: Read,
    logs: Path,
    sessions: dict[str, Any],
    tmp_path: Path,
    resume: bool,
    method: str,
) -> None:
    """23 §Surface: ``open()`` on ``session_id=`` continues the session at
    entry, once, and holds it for every prompt after."""

    cwd = str(tmp_path)
    _ctx1, first = await first_run(context, sessions, cwd, text=["one"])
    sid = first.session_id

    ctx2 = await context()
    agent = Fake(
        command=scenario(
            sessions={**sessions, "resume": resume},
            prompts=[{"text": ["two"]}, {"text": ["three"]}],
            request_log=str(logs),
        ),
        cwd=cwd,
        session_id=sid,
    )
    with bind(ctx2):
        async with agent.open() as held:
            assert held.session_id == sid
            a = await held.prompt("two?")
            b = await held.prompt("three?")

    assert methods(logs)[:2] == ["initialize", method]
    assert methods(logs).count(method) == 1
    assert "session/new" not in methods(logs)
    assert methods(logs).count("session/prompt") == 2
    assert a.text == "two"
    assert b.text == "three"
    assert await transcript(ctx2) == [
        ("notice", f"continuing session {sid}"),
        ("text", "two"),
        ("text", "three"),
    ]
    assert a.session_id == b.session_id == sid
    assert a.stats["session_id"] == b.stats["session_id"] == sid


async def test_the_provider_gives_a_stop_reason_per_prompt_and_stats_only_to_run(
    context: Make,
) -> None:
    """23 §Stats of a held session, D256: every prompt has a final turn; only
    a one-shot ``run()`` is the whole session the provider reports."""

    ctx = await context()
    held_agent = Fake(command=scenario(prompts=[{}, {}]))
    held_agent.stats_provider = Recording(
        stats={"cost": 0.25, "input_tokens": 999, "model": "answered-with"},
        stop_reason=None,
    )
    a, b = await hold(held_agent, ctx, "one", "two")
    sid = a.session_id
    assert held_agent.stats_provider.called == [
        ("final_stop_reason", sid),
        ("final_stop_reason", sid),
    ]
    assert "cost" not in a.stats and "cost" not in b.stats

    ctx2 = await context()
    one_shot = Fake(command=scenario())
    one_shot.stats_provider = Recording(
        stats={"cost": 0.25, "input_tokens": 999, "model": "answered-with"},
        stop_reason=None,
    )
    result = await run(one_shot, ctx2)
    assert one_shot.stats_provider.called == [
        ("final_stop_reason", result.session_id),
        ("stats", result.session_id),
    ]
    assert result.stats["cost"] == 0.25


async def test_an_initialize_failure_raises_from_open_and_never_enters_the_block(
    context: Make, stats_lines: Read
) -> None:
    """23 step 1: an entry that fails stops the child, records one
    ``failed/transport`` entry naming no session, and raises from
    ``open()`` — the block is never entered.

    The child reads the ``initialize`` line and exits without answering,
    so the SDK rejects the pending request when its stdout closes.
    """

    ctx = await context()
    agent = Spy(
        command=[sys.executable, "-c", "import sys; sys.stdin.readline(); sys.exit(1)"]
    )
    entered = False
    with pytest.raises(AgentError, match="connection failed"):
        with bind(ctx):
            async with agent.open():
                entered = True
    assert not entered
    assert stopped(agent)
    lines = await stats_lines(ctx)
    assert len(lines) == 1
    assert "failed (transport)" in lines[0]
    assert "session=" not in lines[0]


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
# The none tier (05 §Tooling tiers, D271)
# --------------------------------------------------------------------------


class Silent(Fake):
    """A façade that wants nothing from its task (05 §Tooling tiers, D271)."""

    tooling = "none"


class Talkative(Spy):
    """A ``none`` class that asks for a value it gave the agent no way to
    deliver — the one configuration error the tier names."""

    tooling = "none"
    output_model = Verdict


async def test_a_none_run_sends_the_prompt_alone(context: Make, logs: Path) -> None:
    """19 §Assembly: the system prompt and the assignment, and nothing that
    names a task, a token or a tool."""

    ctx = await context()
    agent = Silent(command=scenario(text=["hello"], request_log=str(logs)))
    await run(agent, ctx, "say hello")

    prompts = params_of(logs, "session/prompt")
    assert len(prompts) == 1
    text = prompts[0]["prompt"][0]["text"]
    assert text == "You are a test agent.\n\n---\n\n## Your assignment\n\nsay hello"
    assert "## Your task" not in text
    assert ctx.token not in text
    assert "curl" not in text


async def test_a_none_session_carries_no_mcp_server(context: Make, logs: Path) -> None:
    """``none`` is declared, never picked: an agent that advertises MCP
    still gets no server on its session."""

    ctx = await context()
    agent = Silent(command=scenario(advertise_mcp=True, request_log=str(logs)))
    await run(agent, ctx)

    assert params_of(logs, "session/new")[0]["mcpServers"] == []


async def test_a_none_child_gets_no_task_url_or_token(
    context: Make, transcript: Read, monkeypatch: pytest.MonkeyPatch
) -> None:
    """19 §Environment: neither variable is exported on ``none``. An
    ordinary inherited variable still is, so this is the tier's scrub and
    not an empty environment."""

    monkeypatch.setenv("PATH_LIKE_THING", "kept")

    ctx = await context()
    await run(Silent(command=scenario(env_echo=True)), ctx)

    env = echoed(await transcript(ctx))
    assert "ATHANORE_TASK_URL" not in env
    assert "ATHANORE_TASK_TOKEN" not in env
    assert env["PATH_LIKE_THING"] == "kept"


async def test_a_none_result_is_the_text_with_no_output(
    context: Make, stats_lines: Read
) -> None:
    """05 §Tooling tiers: ``text`` is what the agent said, ``output`` is
    ``None``, and the entry is one ordinary ``ok`` — no repairs, because
    the loop never ran, and no zero standing in for them."""

    ctx = await context()
    result = await run(Silent(command=scenario(text=["the", " answer"])), ctx)

    assert result.ok
    assert result.output is None
    assert result.text == "the answer"
    assert result.stop_reason == "end_turn"
    assert result.stats["status"] == "ok"
    assert result.stats["tool_calls"] == 0
    assert "reason" not in result.stats
    assert "repair_turns" not in result.stats

    lines = await stats_lines(ctx)
    assert len(lines) == 1
    assert lines[0].startswith(f"[stats] node={ctx.node} attempt={ctx.attempt} ok")


async def test_a_none_refusal_is_still_a_failed_result(context: Make) -> None:
    """``ok`` is the outcome of the turn: a ``none`` agent that refuses
    fails like any other, with its text and still no output."""

    ctx = await context()
    result = await run(
        Silent(command=scenario(stop_reason="refusal", text=["no"])), ctx
    )

    assert not result.ok
    assert result.error == "refusal"
    assert result.output is None
    assert result.text == "no"


async def test_a_none_class_with_an_output_model_is_refused_before_any_child(
    context: Make, stats_lines: Read
) -> None:
    """05 §Tooling tiers: a body that declares both has asked for a value
    from an agent it gave no way to deliver one. ``AgentError`` leaves
    ``open()`` — and ``run()`` — before a child exists, and nothing is
    recorded because nothing ran."""

    ctx = await context()
    agent = Talkative(command=scenario(text=["never"]))
    entered = False
    with pytest.raises(AgentError, match="declares an output_model on the none tier"):
        with bind(ctx):
            async with agent.open():
                entered = True
    assert not entered
    assert agent.process is None
    assert await stats_lines(ctx) == []

    with pytest.raises(AgentError, match="declares an output_model on the none tier"):
        await run(agent, ctx)
    assert agent.process is None
    assert await stats_lines(ctx) == []


async def test_a_none_run_outside_a_task_is_the_same_prompt(logs: Path) -> None:
    """With no task at all a ``none`` run is the same prompt, the same
    empty server list and the same ``None`` output — and nothing to warn
    about, since the absence was asked for."""

    agent = Silent(command=scenario(text=["hi"], request_log=str(logs)))
    with structlog.testing.capture_logs() as captured:
        result = await agent.run("say hi")

    events = [entry["event"] for entry in captured]
    assert "agent prompt rendered outside a task context" not in events
    text = params_of(logs, "session/prompt")[0]["prompt"][0]["text"]
    assert text == "You are a test agent.\n\n---\n\n## Your assignment\n\nsay hi"
    assert params_of(logs, "session/new")[0]["mcpServers"] == []
    assert result.ok
    assert result.output is None
    assert result.text == "hi"


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
