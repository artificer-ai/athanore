"""How an agent reaches its task: the three tiers (05 §Tooling tiers, D63).

One substrate — the agent HTTP API of 08 — and three adapters over it.
``http`` is the curl block of 19 with the token in a header line;
``mcp`` is a tool server handed to ``session/new`` with the token in *its*
header; ``native`` is a harness extension reading the environment. What
this suite pins is the negotiation between them and the one thing they
are for.

**The token leaves the prompt.** In ``mcp`` and ``native`` it is not in
the text at all, which is asserted over the *whole* rendered prompt
rather than over the block that was supposed to carry it: prompts reach
the model provider, and the absence is the point (12 §Task tokens).

**The tools land on the real endpoint.** The ``mcp`` test is not a
recorded call: the fake connects to the server it was handed with a real
MCP client, calls ``append_log`` and ``submit_result``, and the
assertions are a work-log row and a submission the façade then attaches.
A tier that wrote rows by a shortcut would prove nothing about D63's
"one HTTP substrate".

**The exemption is narrow.** A permission request for the ``athanore``
server is allowed without asking, because a question per log append is a
question nobody reads. A filesystem tool call still opens a request and
still blocks the turn.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel

from athanore.agents.acp import ACPAgent
from athanore.agents.policies import MCP_SERVER_NAME, names_athanore_server
from athanore.engine.context import TaskContext, bind
from athanore.requests.service import RequestService
from athanore.store.rows import RequestView
from athanore.testing import scenario

Make = Callable[..., Awaitable[TaskContext]]
Read = Callable[[TaskContext], Awaitable[list[Any]]]

#: 19, read back out of the document rather than retyped.
DOC = Path(__file__).parents[2] / "docs" / "v1" / "19-agent-prompts.md"

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 10.0


class Verdict(BaseModel):
    """The shape the ``mcp`` tier's ``submit_result`` has to satisfy."""

    verdict: str


class Fake(ACPAgent):
    """A façade with a shape to submit and no opinion about the tier."""

    system_prompt = "You are a test agent."
    output_model = Verdict
    permission_policy = "auto_allow"


def block(heading: str) -> str:
    """The first fenced block under ``heading`` in 19."""

    text = DOC.read_text(encoding="utf-8")
    start = text.index(heading) + len(heading)
    found = re.search(r"```\n(.*?)\n```\n", text[start:], re.S)
    assert found is not None, f"19 has no block under {heading!r}"
    return found.group(1)


def one_line_submission() -> str:
    """19's replacement for the submission block in the tool tiers.

    Inline code in the prose rather than a fenced block, and wrapped
    across two source lines, so the newline is unwrapped here — the text
    is one line and the document is the only copy of it.
    """

    text = DOC.read_text(encoding="utf-8")
    found = re.search(r"replaced\s*\nby one line: `([^`]*)`", text, re.S)
    assert found is not None, "19 no longer states the one-line variant"
    return found.group(1).replace("\n", " ")


async def run(agent: ACPAgent, ctx: TaskContext, prompt: str = "do the work") -> Any:
    """Run ``agent`` as a node body would: bound to its task."""

    with bind(ctx):
        return await agent.run(prompt)


def received(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def prompts(path: Path) -> list[str]:
    """Every prompt the agent was sent, as text."""

    return [
        entry["params"]["prompt"][0]["text"]
        for entry in received(path)
        if entry["method"] == "session/prompt"
    ]


@pytest.fixture
def logs(tmp_path: Path) -> Path:
    return tmp_path / "requests.jsonl"


# --------------------------------------------------------------------------
# Negotiation
# --------------------------------------------------------------------------


async def test_an_advertised_mcp_client_gets_the_mcp_tier(
    served_context: Make, agent_api: Any, logs: Path
) -> None:
    """``auto`` → ``mcp`` when ``initialize`` advertises ``mcpCapabilities.http``."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            advertise_mcp=True, submit={"verdict": "ship it"}, request_log=str(logs)
        )
    )
    await run(agent, ctx)

    servers = [
        entry["params"] for entry in received(logs) if entry["method"] == "session/new"
    ][0]["mcpServers"]
    assert servers == [
        {
            "type": "http",
            "name": MCP_SERVER_NAME,
            "url": f"{ctx.api_base}/mcp/agent",
            "headers": [{"name": "X-Athanore-Token", "value": ctx.token}],
        }
    ]


async def test_no_advertisement_means_the_http_tier(
    served_context: Make, logs: Path
) -> None:
    """The fallback, and the curl block of 19 that comes with it."""

    ctx = await served_context()
    agent = Fake(command=scenario(submit={"verdict": "ship it"}, request_log=str(logs)))
    await run(agent, ctx)

    session_new = [
        entry["params"] for entry in received(logs) if entry["method"] == "session/new"
    ][0]
    assert session_new["mcpServers"] == []

    base = f"{ctx.api_base}/api/agent/tasks/{ctx.task_id}"
    expected = (
        block("### Tier block: `http`")
        .replace("{base}", base)
        .replace("{token}", ctx.token)
    )
    sent = prompts(logs)[0]
    assert expected in sent
    tools = block("### Tier block: `mcp` and `native`")
    assert tools.split(", ask_operator")[0] not in sent, (
        "one tier block, not two: an agent told to curl is not also told it has tools"
    )


async def test_a_declared_tier_is_not_negotiated(
    served_context: Make, logs: Path
) -> None:
    """``native`` cannot be detected, so it is honoured as declared (05)."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            advertise_mcp=True, submit={"verdict": "ship it"}, request_log=str(logs)
        )
    )
    agent.tooling = "native"
    await run(agent, ctx)

    session_new = [
        entry["params"] for entry in received(logs) if entry["method"] == "session/new"
    ][0]
    assert session_new["mcpServers"] == [], "native tools are the harness's, not ours"
    assert block("### Tier block: `mcp` and `native`") not in prompts(logs)[0], (
        "the ask clause is dropped when the policy is off"
    )
    assert prompts(logs)[0].count("get_task (read it)") == 1


async def test_a_declared_mcp_tier_needs_no_advertisement(
    served_context: Make, agent_api: Any, logs: Path
) -> None:
    """``mcpCapabilities`` answers ``auto`` and nothing else (05 §Tooling tiers).

    A class that says ``mcp`` is a class whose agent is known to speak
    it — an adapter that under-reports its capabilities, or a harness the
    negotiation predates — and the tier it declared is the tier it gets.
    """

    ctx = await served_context()
    agent = Fake(command=scenario(submit={"verdict": "ship it"}, request_log=str(logs)))
    agent.tooling = "mcp"
    await run(agent, ctx)

    session_new = [
        entry["params"] for entry in received(logs) if entry["method"] == "session/new"
    ][0]
    assert session_new["mcpServers"] == [
        {
            "type": "http",
            "name": MCP_SERVER_NAME,
            "url": f"{ctx.api_base}/mcp/agent",
            "headers": [{"name": "X-Athanore-Token", "value": ctx.token}],
        }
    ]
    assert ctx.token not in prompts(logs)[0]


async def test_a_declared_http_tier_is_not_upgraded(
    served_context: Make, logs: Path
) -> None:
    """The other direction: an advertisement does not override a declaration."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            advertise_mcp=True, submit={"verdict": "ship it"}, request_log=str(logs)
        )
    )
    agent.tooling = "http"
    await run(agent, ctx)

    session_new = [
        entry["params"] for entry in received(logs) if entry["method"] == "session/new"
    ][0]
    assert session_new["mcpServers"] == [], "no server was asked for"
    assert f"-H 'X-Athanore-Token: {ctx.token}'" in prompts(logs)[0]


async def test_http_is_forced_without_a_task_to_point_at(logs: Path) -> None:
    """The ``mcp`` server is scoped to a task token; with no task there is none."""

    agent = Fake(
        command=scenario(advertise_mcp=True, request_log=str(logs)),
    )
    agent.output_model = None
    await agent.run("standalone")

    session_new = [
        entry["params"] for entry in received(logs) if entry["method"] == "session/new"
    ][0]
    assert session_new["mcpServers"] == []


# --------------------------------------------------------------------------
# The prompt each tier carries
# --------------------------------------------------------------------------


@pytest.mark.parametrize("tier", ["mcp", "native"])
async def test_the_tool_tiers_carry_no_token(
    served_context: Make, logs: Path, tier: Literal["mcp", "native"]
) -> None:
    """12 §Task tokens: the whole prompt, not the block it was expected in."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            advertise_mcp=True, submit={"verdict": "ship it"}, request_log=str(logs)
        )
    )
    agent.tooling = tier
    await run(agent, ctx)

    sent = prompts(logs)[0]
    assert ctx.token not in sent
    assert "curl" not in sent
    tools = block("### Tier block: `mcp` and `native`")
    assert tools.split(", ask_operator")[0] in sent
    assert one_line_submission() in sent
    assert "The JSON must conform to this schema" not in sent


async def test_ask_operator_is_listed_only_when_the_policy_is_on(
    served_context: Make, logs: Path
) -> None:
    """19: the tool an agent may not call is not one it is told about."""

    class Asking(Fake):
        ask_policy = "http"

    ctx = await served_context()
    agent = Asking(
        command=scenario(
            advertise_mcp=True, submit={"verdict": "ship it"}, request_log=str(logs)
        )
    )
    await run(agent, ctx)

    sent = prompts(logs)[0]
    assert block("### Tier block: `mcp` and `native`") in sent
    assert ctx.token not in sent, "the ask block is the tool's description, not curl"
    assert block("## Ask instructions") not in sent


async def test_the_http_tier_still_carries_the_token(
    served_context: Make, logs: Path
) -> None:
    """The tier that has no other way to hand one over still hands one over."""

    ctx = await served_context()
    agent = Fake(command=scenario(submit={"verdict": "ship it"}, request_log=str(logs)))
    await run(agent, ctx)

    assert f"-H 'X-Athanore-Token: {ctx.token}'" in prompts(logs)[0]


# --------------------------------------------------------------------------
# The `mcp` tier, end to end
# --------------------------------------------------------------------------


async def test_mcp_tools_reach_the_task_through_the_real_endpoint(
    served_context: Make, agent_api: Any, work_log: Read
) -> None:
    """05 §Tooling tiers: the agent's four capabilities, as tool calls.

    The fake connects to the server it was handed with the real ``mcp``
    client and calls two of the tools; the tools POST to the agent API
    with the task token; the façade then attaches the submission the
    endpoint stored. Nothing in that chain is a shortcut.
    """

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            advertise_mcp=True,
            mcp_calls=[
                {"tool": "append_log", "args": {"text": "from the agent"}},
                {"tool": "submit_result", "args": {"payload": {"verdict": "ship it"}}},
            ],
        )
    )
    result = await run(agent, ctx)

    assert result.ok
    assert result.output.verdict == "ship it"
    assert "from the agent" in await work_log(ctx)
    assert ctx.token in agent_api.mcp_tokens, "the token travelled in the header"
    assert agent_api.tokens == [ctx.token, ctx.token], "and then over the HTTP hop"


async def test_the_mcp_results_are_in_the_transcript(
    served_context: Make, transcript: Read
) -> None:
    """A tool call the agent made is a tool call an operator can read (07)."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            advertise_mcp=True,
            mcp_calls=[
                {"tool": "submit_result", "args": {"payload": {"verdict": "y"}}}
            ],
        )
    )
    await run(agent, ctx)

    chunks = await transcript(ctx)
    assert ("tool_call", "submit_result") in chunks
    assert ("tool_result", "submit: 200") in chunks


# --------------------------------------------------------------------------
# The permission exemption
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    ["mcp__athanore__append_log", "athanore__append_log", "athanore:submit_result"],
)
def test_the_spellings_of_our_own_server_are_recognised(title: str) -> None:
    """05: that server by name, in the shapes adapters actually use."""

    assert names_athanore_server(_ToolCall(title))


@pytest.mark.parametrize(
    "title",
    [
        "mcp__other__append_log",
        "append_log",
        "edit athanore/agents/acp.py",
        "",
        None,
    ],
)
def test_nothing_else_is_exempt(title: str | None) -> None:
    """Not another MCP server, not a tool that merely mentions us."""

    assert not names_athanore_server(_ToolCall(title))


class _ToolCall:
    """The one field the exemption reads, as ACP carries it."""

    def __init__(self, title: str | None) -> None:
        self.title = title
        self.kind: str | None = "other"
        self.raw_input: Any = None


async def test_our_own_server_is_allowed_without_asking(
    claimed_context: Make,
    agent_api: Any,
    request_service: RequestService,
    transcript: Read,
) -> None:
    """A log append never becomes a question for the operator (05)."""

    ctx = await claimed_context(api_base=agent_api.base)
    agent_api.attach(ctx)
    agent = Fake(
        command=scenario(
            advertise_mcp=True,
            permissions=[
                {
                    "title": "mcp__athanore__append_log",
                    "options": [
                        {"kind": "reject_once", "option_id": "no"},
                        {"kind": "allow_once", "option_id": "yes"},
                    ],
                }
            ],
            submit={"verdict": "ship it"},
        )
    )
    agent.permission_policy = "ask"
    result = await run(agent, ctx)

    assert result.ok
    assert await request_service.list_for_run(ctx.run_id) == []
    assert ("tool_call", "mcp__athanore__append_log") not in await transcript(ctx), (
        "a permission is not a tool-call update; the agent's own call is"
    )


async def test_a_filesystem_permission_still_asks(
    claimed_context: Make,
    agent_api: Any,
    request_service: RequestService,
) -> None:
    """The exemption is narrow: everything else blocks the turn on a person."""

    ctx = await claimed_context(api_base=agent_api.base)
    agent_api.attach(ctx)
    agent = Fake(
        command=scenario(
            advertise_mcp=True,
            permissions=[
                {
                    "title": "edit /etc/passwd",
                    "options": [
                        {"kind": "reject_once", "option_id": "no"},
                        {"kind": "allow_once", "option_id": "yes"},
                    ],
                }
            ],
            submit={"verdict": "ship it"},
        )
    )
    agent.permission_policy = "ask"
    task = asyncio.get_running_loop().create_task(run(agent, ctx))

    async with asyncio.timeout(DEADLINE):
        opened = await _opened(request_service, ctx)
        assert opened.prompt == "permission: edit /etc/passwd"
        await request_service.answer(opened.id, option_id="yes")
        result = await task

    assert result.ok


async def _opened(service: RequestService, ctx: TaskContext) -> RequestView:
    """The one request this attempt opened, once it has opened it."""

    while True:
        views = await service.list_for_run(ctx.run_id)
        if views:
            assert len(views) == 1, "one question at a time in this suite"
            return views[0]
        await asyncio.sleep(0.005)
