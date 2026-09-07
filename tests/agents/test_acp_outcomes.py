"""How an agent run ends, and what it costs (05 §AgentResult, T039a).

The other half of :class:`~athanore.agents.acp.ACPAgent`: the repair
loop, the outcome mapping, the cleanup and the one stats entry. Still on
``FakeACPAgent`` and a real store, because the questions are *did a row
get written*, *is the child gone*, and *how many entries are there*.

Two rules are the reason the suite exists, and both are shapes the MVP
got wrong:

**A refusal is an answer, a timeout is not.** ``refusal``, ``cancelled``
and a truncated final turn come back as a ``failed`` result the body
routes on. A timeout, a transport failure and a missing submission raise
:exc:`~athanore.agents.base.AgentError`, because there is no value to
route with — and rule 3 puts the retry in the engine, never here.

**Exactly one stats entry, on every path.** Success, failure, timeout,
refusal and a cancelled shutdown: five exits, one ``[stats]`` line each.
The ``finally`` that records it is also the one that stops the child, so
the count is asserted from the work log rather than from a return value —
a run that raised still has to have paid its bill.

Ported from the subprocess halves of the MVP's ``test_submissions.py``,
``test_acp_stats.py`` and ``test_agents.py``; the parts that need no
subprocess are ``test_policies.py`` and ``test_submissions_unit.py``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from athanore.agents.acp import ACPAgent
from athanore.agents.base import AgentError
from athanore.engine.context import TaskContext, bind
from athanore.events.names import EventName
from athanore.requests.service import RequestService
from athanore.store.rows import RequestView
from athanore.store.uow import Store
from athanore.testing import FakeStatsProvider, scenario

Make = Callable[..., Awaitable[TaskContext]]
Read = Callable[[TaskContext], Awaitable[list[Any]]]

#: The fuse on every wait here. Reached only when something is broken.
DEADLINE = 10.0


class Verdict(BaseModel):
    """The shape this suite's agents are asked to submit."""

    verdict: str
    notes: str = ""


class Fake(ACPAgent):
    """A façade with an ``output_model``, so repairs are on the table."""

    system_prompt = "You are a test agent."
    output_model = Verdict
    permission_policy = "auto_allow"


class Spy(Fake):
    """A ``Fake`` that keeps the child, so a test can assert it is gone.

    The subprocess is deliberately private — it belongs to one ``run()``
    and nothing outside it may hold one — so the only honest way to
    assert "no zombie" is to look over the façade's shoulder as it
    spawns.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.process: asyncio.subprocess.Process | None = None

    async def _spawn(self, session: Any, settings: Any, ctx: Any) -> None:
        await super()._spawn(session, settings, ctx)
        self.process = session.process


async def run(agent: ACPAgent, ctx: TaskContext, prompt: str = "do the work") -> Any:
    """Run ``agent`` as a node body would: bound to its task."""

    with bind(ctx):
        return await agent.run(prompt)


async def spawned(agent: Spy) -> asyncio.subprocess.Process:
    """Wait until ``agent`` has a child, and hand it over.

    A poll rather than an event: the thing being waited for is a private
    step inside another task's ``run()``, and adding a hook to the façade
    for a test to synchronise on would be the test changing the subject.
    """

    while agent.process is None:  # noqa: ASYNC110
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.1)
    return agent.process


async def events_named(store: Store, ctx: TaskContext, name: str) -> list[Any]:
    """Every stored event of one name for this run, oldest first."""

    async with store.reader() as reader:
        return await reader.events.list_after(
            0, limit=1000, run_id=ctx.run_id, patterns=[name]
        )


# --------------------------------------------------------------------------
# The repair loop
# --------------------------------------------------------------------------


async def test_a_valid_submission_needs_no_repair(
    served_context: Make, store: Store, transcript: Read
) -> None:
    """The loop is not entered when there is nothing to repair."""

    ctx = await served_context()
    agent = Fake(command=scenario(submit={"verdict": "ship it"}))
    result = await run(agent, ctx)

    assert result.ok
    assert isinstance(result.output, Verdict)
    assert result.output.verdict == "ship it"
    assert await events_named(store, ctx, EventName.submission_repair) == []
    assert [kind for kind, _ in await transcript(ctx)] == []


async def test_a_missing_submission_is_asked_for_again(
    served_context: Make, store: Store, transcript: Read, logs: Path
) -> None:
    """19 §Repair turn: same session, and the second submission wins."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(repair_submit={"verdict": "second"}, request_log=str(logs))
    )
    result = await run(agent, ctx)

    assert result.ok
    assert result.output.verdict == "second"
    assert result.stats["repair_turns"] == 1

    prompts = [
        entry["params"]
        for entry in received(logs)
        if entry["method"] == "session/prompt"
    ]
    assert len(prompts) == 2
    assert prompts[0]["sessionId"] == prompts[1]["sessionId"], "the same session"
    assert prompts[1]["prompt"][0]["text"].startswith(
        "Your turn ended, but no valid structured result was received for "
        "this task (nothing was submitted)."
    )

    repairs = await events_named(store, ctx, EventName.submission_repair)
    assert [event.data["turn"] for event in repairs] == [1]
    assert repairs[0].data["reason"] == "nothing_submitted"
    assert [kind for kind, _ in await transcript(ctx)] == ["notice"]


async def test_a_rejected_submission_is_quoted_back(
    served_context: Make, store: Store
) -> None:
    """The repair turn carries the 422 the endpoint answered with (19)."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(submit={"wrong": "shape"}, repair_submit={"verdict": "fixed"})
    )
    result = await run(agent, ctx)

    assert result.ok
    assert result.output.verdict == "fixed"
    repairs = await events_named(store, ctx, EventName.submission_repair)
    assert [event.data["reason"] for event in repairs] == ["rejected"]


async def test_the_repair_loop_stops_at_max_repair_turns(
    served_context: Make, store: Store, logs: Path
) -> None:
    """A budget, not a loop: an agent that never submits is a failed run."""

    ctx = await served_context()
    agent = Fake(command=scenario(request_log=str(logs)))
    agent.max_repair_turns = 2

    with pytest.raises(AgentError, match="valid submission"):
        await run(agent, ctx)

    prompts = [entry for entry in received(logs) if entry["method"] == "session/prompt"]
    assert len(prompts) == 1 + 2, "the first turn, then two repairs and no more"
    repairs = await events_named(store, ctx, EventName.submission_repair)
    assert [event.data["turn"] for event in repairs] == [1, 2]


async def test_no_repair_turns_when_the_budget_is_zero(
    served_context: Make, logs: Path
) -> None:
    """``max_repair_turns=0`` is a façade that asks once and accepts the answer."""

    ctx = await served_context()
    agent = Fake(command=scenario(request_log=str(logs)))
    agent.max_repair_turns = 0

    with pytest.raises(AgentError):
        await run(agent, ctx)

    assert len([e for e in received(logs) if e["method"] == "session/prompt"]) == 1


async def test_a_refusal_is_not_repaired(served_context: Make, store: Store) -> None:
    """A turn that refused cannot succeed on a second ask; the budget stands."""

    ctx = await served_context()
    result = await run(Fake(command=scenario(stop_reason="refusal")), ctx)

    assert not result.ok
    assert await events_named(store, ctx, EventName.submission_repair) == []


# --------------------------------------------------------------------------
# Outcome mapping
# --------------------------------------------------------------------------


@pytest.mark.parametrize("stop", ["refusal", "cancelled"])
async def test_a_refusal_returns_a_failed_result(
    served_context: Make, stats_lines: Read, stop: str
) -> None:
    """05 §AgentResult: an answer the body decides about, not an exception."""

    ctx = await served_context()
    result = await run(Fake(command=scenario(stop_reason=stop, text=["no"])), ctx)

    assert not result.ok
    assert result.status == "failed"
    assert result.error == stop
    assert result.stop_reason == stop
    assert result.text == "no"
    assert result.stats["reason"] == stop
    assert (await stats_lines(ctx))[0].startswith(
        f"[stats] node=build attempt=1 failed ({stop})"
    )


async def test_truncation_is_the_providers_to_report(
    served_context: Make, stats_lines: Read
) -> None:
    """D27: a turn consumed by reasoning is reported ``end_turn`` by ACP.

    Only the agent's own session file knows it was cut off at the token
    limit, so the detection lives behind
    :class:`~athanore.agents.stats.SessionStatsProvider` and nothing in
    the package reads a vendor's home directory.
    """

    ctx = await served_context()
    agent = Fake(command=scenario(submit={"verdict": "ship it"}))
    agent.stats_provider = FakeStatsProvider(stop_reason="length")
    result = await run(agent, ctx)

    assert not result.ok
    assert result.error == "truncated"
    assert result.stop_reason == "end_turn", "ACP thought the turn was fine"
    assert "failed (truncated)" in (await stats_lines(ctx))[0]


async def test_a_provider_that_knows_nothing_does_not_fail_the_run(
    served_context: Make,
) -> None:
    """Not determined is not truncated: a guess here fails runs that worked."""

    ctx = await served_context()
    agent = Fake(command=scenario(submit={"verdict": "ship it"}))
    agent.stats_provider = FakeStatsProvider(stop_reason=None)

    assert (await run(agent, ctx)).ok


async def test_a_missing_submission_raises_after_the_repairs(
    served_context: Make, stats_lines: Read
) -> None:
    """05: there is no value to route on, so the body is not asked to."""

    ctx = await served_context()
    agent = Fake(command=scenario(text=["I forgot"]))
    agent.max_repair_turns = 0

    with pytest.raises(AgentError):
        await run(agent, ctx)

    assert "failed (no_submission)" in (await stats_lines(ctx))[0]


async def test_an_agent_with_no_output_model_needs_no_submission(
    served_context: Make,
) -> None:
    """Without a declared shape, nothing was ever required (05 §Submissions)."""

    class Chatty(ACPAgent):
        permission_policy = "auto_allow"

    ctx = await served_context()
    result = await run(Chatty(command=scenario(text=["done"])), ctx)

    assert result.ok
    assert result.output is None


# --------------------------------------------------------------------------
# Timeout, transport, cancellation
# --------------------------------------------------------------------------


async def test_a_timeout_kills_the_child_and_raises(
    served_context: Make, stats_lines: Read
) -> None:
    """05: a timeout is an :exc:`AgentError`, and it leaves no process.

    ``returncode is not None`` is the whole assertion about zombies: a
    façade that raised without waiting on the child would leave one per
    timed-out attempt, and a long-running server would collect them.
    """

    ctx = await served_context()
    agent = Spy(command=scenario(sleep_s=30, submit={"verdict": "too late"}))
    agent.timeout = 0.5

    with pytest.raises(AgentError, match="did not finish"):
        await run(agent, ctx)

    assert agent.process is not None
    assert agent.process.returncode is not None, "no zombie"
    lines = await stats_lines(ctx)
    assert len(lines) == 1, "the timeout exit pays its bill once"
    assert "failed (timeout)" in lines[0]


async def test_a_command_that_does_not_exist_is_a_transport_failure(
    served_context: Make, stats_lines: Read
) -> None:
    """A spawn that fails is the same outcome as a connection that dies."""

    ctx = await served_context()

    with pytest.raises(AgentError, match="connection failed"):
        await run(Fake(command=["athanore-no-such-agent-binary"]), ctx)

    assert "failed (transport)" in (await stats_lines(ctx))[0]


async def test_a_policy_that_cannot_be_honoured_fails_the_run(
    served_context: Make, stats_lines: Read
) -> None:
    """D10: the SDK would turn this into an error response and an ``ok`` run.

    An agent offering no way to say yes, under ``auto_allow``. The
    exception is raised inside a callback, so the client records it and
    ``run()`` raises it once the turn ends — the failure the MVP
    reported as success.
    """

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            permissions=[{"options": [{"kind": "reject_once"}]}],
            submit={"verdict": "ship it"},
        )
    )

    with pytest.raises(AgentError, match="auto_allow"):
        await run(agent, ctx)

    assert "failed (transport)" in (await stats_lines(ctx))[0]


async def test_a_shutdown_cancel_still_records(
    served_context: Make, stats_lines: Read
) -> None:
    """A cancelled attempt paid for the tokens it spent (05 §Stats entry)."""

    ctx = await served_context()
    agent = Spy(command=scenario(sleep_s=30, submit={"verdict": "never"}))
    task = asyncio.get_running_loop().create_task(run(agent, ctx))

    async with asyncio.timeout(DEADLINE):
        process = await spawned(agent)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert process.returncode is not None, "no zombie"
    lines = await stats_lines(ctx)
    assert len(lines) == 1, "the cancelled exit pays its bill once, not twice"
    assert "failed (shutdown)" in lines[0]


# --------------------------------------------------------------------------
# The two questions an agent asks, over the wire
# --------------------------------------------------------------------------


async def test_a_form_elicitation_reaches_the_operator_and_comes_back(
    claimed_context: Make,
    agent_api: Any,
    request_service: RequestService,
    tmp_path: Path,
) -> None:
    """06 §The model, through ACP: the bridge, and the answer the agent gets.

    ``test_policies.py`` asserts the request row and its registered
    validator; what only a subprocess can show is the round trip — the
    turn blocked on a person, and the ``accept`` that reached the agent.
    """

    responses = tmp_path / "responses.jsonl"
    ctx = await claimed_context(api_base=agent_api.base)
    agent_api.attach(ctx)
    agent = Fake(
        command=scenario(
            elicitations=[
                {
                    "mode": "form",
                    "schema": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                    },
                }
            ],
            submit={"verdict": "ship it"},
            response_log=str(responses),
        )
    )
    task = asyncio.get_running_loop().create_task(run(agent, ctx))

    async with asyncio.timeout(DEADLINE):
        opened = await _opened(request_service, ctx)
        assert opened.mode == "form"
        assert opened.schema_ is not None
        assert opened.schema_["required"] == ["name"]
        await request_service.answer(opened.id, value={"name": "the operator"})
        result = await task

    assert result.ok
    assert answers(responses) == [
        {"action": "accept", "content": {"name": "the operator"}}
    ]


async def test_a_url_elicitation_is_declined(
    claimed_context: Make,
    agent_api: Any,
    request_service: RequestService,
    tmp_path: Path,
) -> None:
    """05 §Policies: URL mode has the operator visit a link for the agent.

    The request channel does not model that, so it is declined — a
    decision, not a failure: the turn goes on and the run completes.
    """

    responses = tmp_path / "responses.jsonl"
    ctx = await claimed_context(api_base=agent_api.base)
    agent_api.attach(ctx)
    agent = Fake(
        command=scenario(
            elicitations=[{"mode": "url"}],
            submit={"verdict": "ship it"},
            response_log=str(responses),
        )
    )
    result = await run(agent, ctx)

    assert result.ok
    assert await request_service.list_for_run(ctx.run_id) == []
    assert answers(responses) == [{"action": "decline"}]


async def _opened(service: RequestService, ctx: TaskContext) -> RequestView:
    """The one request this attempt opened, once it has opened it."""

    while True:
        views = await service.list_for_run(ctx.run_id)
        if views:
            assert len(views) == 1, "one question at a time in this suite"
            return views[0]
        await asyncio.sleep(0.005)


# --------------------------------------------------------------------------
# Stats: exactly one entry, on each of five exits
# --------------------------------------------------------------------------


async def test_a_successful_run_records_one_entry(
    served_context: Make, store: Store, stats_lines: Read
) -> None:
    """05 §Stats entry: the line, the column and the event, once."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            submit={"verdict": "ship it"},
            tool_calls=2,
            usage={"input": 1200, "output": 34},
        )
    )
    agent.model = "fake/fake-model"
    result = await run(agent, ctx)

    assert len(await stats_lines(ctx)) == 1
    assert len(await events_named(store, ctx, EventName.agent_stats)) == 1
    assert result.stats["input_tokens"] == 1200
    assert result.stats["output_tokens"] == 34
    assert result.stats["total_tokens"] == 1234
    assert result.stats["model"] == "fake/fake-model"
    assert result.stats["session_id"]
    assert "duration_s" in result.stats


async def test_usage_is_summed_over_the_turns_of_a_run(served_context: Make) -> None:
    """A repair turn is part of the same run, and it cost tokens too."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            repair_submit={"verdict": "second"}, usage={"input": 100, "output": 10}
        )
    )
    result = await run(agent, ctx)

    assert result.stats["input_tokens"] == 200, "two turns"
    assert result.stats["output_tokens"] == 20


async def test_the_provider_supplies_cost_and_the_model_that_answered(
    served_context: Make, stats_lines: Read
) -> None:
    """05 §Stats entry: ACP wins for tokens, the provider for cost."""

    ctx = await served_context()
    agent = Fake(
        command=scenario(
            submit={"verdict": "ship it"}, usage={"input": 10, "output": 2}
        )
    )
    agent.model = "asked-for"
    agent.stats_provider = FakeStatsProvider(
        {"model": "answered-with", "input_tokens": 999, "cost": 0.25}
    )
    result = await run(agent, ctx)

    assert result.stats["input_tokens"] == 10, "ACP wins for tokens"
    assert result.stats["cost"] == 0.25
    assert result.stats["model"] == "answered-with"
    assert "cost=$0.2500" in (await stats_lines(ctx))[0]


async def test_unknown_measurements_are_omitted_not_zeroed(
    served_context: Make,
) -> None:
    """`AGENTS.md` §Real data only: no ``usage``, no token fields."""

    ctx = await served_context()
    result = await run(Fake(command=scenario(submit={"verdict": "ship it"})), ctx)

    assert "input_tokens" not in result.stats
    assert "output_tokens" not in result.stats
    assert "cost" not in result.stats


@pytest.mark.parametrize(
    ("script", "raises"),
    [
        ({"submit": {"verdict": "ship it"}}, False),
        ({"stop_reason": "refusal"}, False),
        ({}, True),
    ],
    ids=["success", "refusal", "no_submission"],
)
async def test_one_entry_per_run_whatever_happened(
    served_context: Make, stats_lines: Read, script: dict[str, Any], raises: bool
) -> None:
    """The ``finally`` records once, and only once, on every exit it has.

    Three of T039a's five here; the other two need a child to look at
    and a task to cancel, so the count is asserted beside the zombie in
    ``test_a_timeout_kills_the_child_and_raises`` and
    ``test_a_shutdown_cancel_still_records``.
    """

    ctx = await served_context()
    agent = Fake(command=scenario(**script))
    agent.max_repair_turns = 0

    if raises:
        with pytest.raises(AgentError):
            await run(agent, ctx)
    else:
        await run(agent, ctx)

    assert len(await stats_lines(ctx)) == 1


async def test_two_agents_in_one_body_record_two_entries(
    served_context: Make, stats_lines: Read
) -> None:
    """One entry per ``run()``, not one per attempt (05 §Stats entry).

    Also the reason the façade **flushes** the transcript rather than
    closing it: the second agent still has somewhere to write.
    """

    ctx = await served_context()
    with bind(ctx):
        first = await Fake(command=scenario(submit={"verdict": "one"})).run("a")
        second = await Fake(command=scenario(submit={"verdict": "two"})).run("b")

    assert first.output.verdict == "one"
    assert second.output.verdict == "two"
    assert len(await stats_lines(ctx)) == 2


def received(path: Path) -> list[dict[str, Any]]:
    """The requests the fake logged, in order."""

    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def answers(path: Path) -> list[Any]:
    """What this client answered the requests the *agent* initiated with.

    The fake's ``response_log`` carries its HTTP statuses too (13
    §Fakes), so the JSON-RPC responses are the entries with a ``result``.
    """

    return [entry["result"] for entry in received(path) if "result" in entry]


@pytest.fixture
def logs(tmp_path: Path) -> Path:
    """Where the fake writes the requests it received, one JSON per line."""

    return tmp_path / "requests.jsonl"
