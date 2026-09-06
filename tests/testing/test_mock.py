"""`MockAgent`, `StatsMockAgent`, `FakeStatsProvider` (05 §Testing doubles).

The subject is that these are *doubles*, not shortcuts: what they leave
out is the subprocess and nothing else. A submission goes through the
predicate the endpoint applies and lands in the table a body reads; a
misfit rejects and leaves the rejection the repair turn quotes; a stats
entry is built by the builder the façade uses and recorded exactly once,
on the failure path as well as the success path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from pydantic import BaseModel

from athanore.agents.base import AgentError
from athanore.agents.stats import SessionStats
from athanore.engine.context import TaskContext, bind
from athanore.store.uow import Store
from athanore.testing import FakeStatsProvider, MockAgent, StatsMockAgent

Context = Callable[..., Awaitable[TaskContext]]


class Review(BaseModel):
    verdict: str
    notes: str = ""


class Reviewer(MockAgent):
    output_model = Review


# --------------------------------------------------------------------------
# MockAgent
# --------------------------------------------------------------------------


async def test_output_is_returned_without_submitting_anything(
    context: Context, store: Store
) -> None:
    ctx = await context()
    with bind(ctx):
        result = await MockAgent(output={"n": 1}).run("go")
    assert result.ok
    assert result.output == {"n": 1}
    assert result.text == "mock agent output"
    async with store.reader() as reader:
        assert await reader.submissions.latest(ctx.task_id) is None


async def test_the_prompt_is_kept_for_the_tests_that_are_about_it(
    context: Context,
) -> None:
    agent = MockAgent(output=1)
    with bind(await context()):
        await agent.run("the assignment")
    assert agent.prompt == "the assignment"


async def test_a_submission_is_stored_and_attached_as_the_declared_model(
    context: Context, store: Store
) -> None:
    ctx = await context()
    with bind(ctx):
        result = await Reviewer(submit={"verdict": "approve"}).run()
    assert isinstance(result.output, Review)
    assert result.output.verdict == "approve"
    async with store.reader() as reader:
        row = await reader.submissions.latest(ctx.task_id)
    assert row is not None and row.payload == {"verdict": "approve"}


async def test_a_pydantic_payload_is_submitted_as_json(
    context: Context, store: Store
) -> None:
    ctx = await context()
    with bind(ctx):
        await Reviewer(submit=Review(verdict="reject", notes="no")).run()
    async with store.reader() as reader:
        row = await reader.submissions.latest(ctx.task_id)
    assert row is not None and row.payload == {"verdict": "reject", "notes": "no"}


class Capturing(Reviewer):
    """A reviewer that keeps the rejection its own run declared.

    ``ctx.last_rejection`` belongs to the run: ``Agent.declare`` restores
    what was there before on the way out, so a repair loop sees it and a
    caller does not. Reading it from inside is what the loop of T039a
    does.
    """

    rejection: dict[str, Any] | None = None

    async def _submit_payload(self, ctx: TaskContext | None) -> None:
        await super()._submit_payload(ctx)
        self.rejection = None if ctx is None else ctx.last_rejection


async def test_a_misfit_submission_rejects_and_leaves_the_repair_material(
    context: Context, store: Store
) -> None:
    """Exactly what the endpoint does with a 422 (05 §Submissions, T045)."""

    ctx = await context()
    agent = Capturing(submit={"wrong": 1})
    with bind(ctx), pytest.raises(AgentError, match="valid submission"):
        await agent.run()
    rejection = agent.rejection
    assert rejection is not None
    assert rejection["payload"] == {"wrong": 1}
    assert rejection["errors"][0]["loc"] == ["verdict"]
    assert rejection["schema"]["title"] == "Review"
    async with store.reader() as reader:
        assert await reader.submissions.latest(ctx.task_id) is None


async def test_a_submission_needs_no_model_when_none_is_declared(
    context: Context,
) -> None:
    ctx = await context()
    with bind(ctx):
        result = await MockAgent(submit={"anything": True}).run()
    assert result.output == {"anything": True}


async def test_log_appends_the_deliverable_to_the_run_log(
    context: Context, store: Store
) -> None:
    ctx = await context()
    with bind(ctx):
        await MockAgent(log="the deliverable", output=1).run()
    async with store.reader() as reader:
        entries = await reader.log.list(ctx.run_id)
    assert [(entry.author, entry.text) for entry in entries] == [
        ("agent", "the deliverable")
    ]


async def test_stream_writes_the_transcript_with_its_kinds(
    context: Context, store: Store
) -> None:
    ctx = await context()
    with bind(ctx):
        await MockAgent(
            stream=["thinking", ("tool_call", "ran the gate")], output=1
        ).run()
        await ctx.services.stream.close()
    async with store.reader() as reader:
        chunks = await reader.stream.list_after(ctx.task_id)
    assert [(chunk.kind, chunk.text) for chunk in chunks] == [
        ("text", "thinking"),
        ("tool_call", "ran the gate"),
    ]


async def test_fail_raises_the_error_a_body_sees(context: Context) -> None:
    with bind(await context()), pytest.raises(AgentError, match="the child died"):
        await MockAgent(fail="the child died").run()


async def test_every_argument_may_be_a_callable(context: Context, store: Store) -> None:
    """A body that runs the same agent twice scripts the attempts."""

    turns = iter(["first", "second"])
    agent = MockAgent(log=lambda: next(turns), output=lambda: 7)
    ctx = await context()
    with bind(ctx):
        assert (await agent.run()).output == 7
        assert (await agent.run()).output == 7
    async with store.reader() as reader:
        entries = await reader.log.list(ctx.run_id)
    assert [entry.text for entry in entries] == ["first", "second"]


async def test_the_declaration_is_restored_on_the_way_out(
    context: Context,
) -> None:
    """A body may run two agents in sequence (05 §Session lifecycle, 3)."""

    ctx = await context()
    with bind(ctx):
        await Reviewer(submit={"verdict": "approve"}).run()
        assert ctx.output_model is None
        assert ctx.last_rejection is None


async def test_a_submission_outside_a_task_context_is_an_error() -> None:
    with pytest.raises(AgentError, match="needs a task context"):
        await MockAgent(submit={"a": 1}).run()


# --------------------------------------------------------------------------
# StatsMockAgent
# --------------------------------------------------------------------------


async def test_one_entry_is_recorded_per_run_with_the_scripted_numbers(
    context: Context, store: Store
) -> None:
    ctx = await context(attempt=2)
    stats = {
        "model": "llama-server/qwen3",
        "input_tokens": 12406,
        "output_tokens": 1204,
        "total_tokens": 13610,
        "cost": 0.0,
        "tool_calls": 23,
        "session_id": "01a01646",
    }
    with bind(ctx):
        result = await StatsMockAgent(stats=stats, output=1).run()
    assert result.stats["node"] == "build"
    assert result.stats["attempt"] == 2
    assert result.stats["status"] == "ok"
    assert result.stats["model"] == "llama-server/qwen3"
    assert result.stats["input_tokens"] == 12406
    assert result.stats["tool_calls"] == 23
    async with store.reader() as reader:
        task = await reader.tasks.get(ctx.task_id)
        entries = await reader.log.list(ctx.run_id)
    assert task is not None and task.stats == result.stats
    lines = [entry for entry in entries if entry.kind == "stats"]
    assert len(lines) == 1
    assert lines[0].author == "engine"
    assert "tokens=12,406 in / 1,204 out / 13,610 total" in lines[0].text


async def test_an_unknown_number_is_omitted_and_never_zero_filled(
    context: Context,
) -> None:
    with bind(await context()):
        result = await StatsMockAgent(output=1).run()
    for field in ("model", "cost", "input_tokens", "tool_calls", "reason"):
        assert field not in result.stats
    assert result.stats["duration_s"] == 0


async def test_a_failure_records_its_entry_before_it_raises(
    context: Context, store: Store
) -> None:
    ctx = await context()
    with bind(ctx), pytest.raises(AgentError, match="refusal"):
        await StatsMockAgent(fail="refusal", stats={"tool_calls": 0}).run()
    async with store.reader() as reader:
        task = await reader.tasks.get(ctx.task_id)
    assert task is not None and task.stats is not None
    assert task.stats["status"] == "failed"
    assert task.stats["reason"] == "refusal"
    assert task.stats["tool_calls"] == 0


async def test_a_plain_failure_is_a_transport_failure(
    context: Context, store: Store
) -> None:
    ctx = await context()
    with bind(ctx), pytest.raises(AgentError):
        await StatsMockAgent(fail=True).run()
    async with store.reader() as reader:
        task = await reader.tasks.get(ctx.task_id)
    assert task is not None and task.stats is not None
    assert task.stats["reason"] == "transport"


async def test_an_agent_error_from_the_body_is_still_recorded(
    context: Context, store: Store
) -> None:
    """A missing submission fails the run — and the run still has numbers."""

    class Missing(StatsMockAgent):
        output_model = Review

    ctx = await context()
    with bind(ctx), pytest.raises(AgentError, match="valid submission"):
        await Missing(stats={"session_id": "abc"}).run()
    async with store.reader() as reader:
        task = await reader.tasks.get(ctx.task_id)
    assert task is not None and task.stats is not None
    assert task.stats["status"] == "failed"
    assert task.stats["reason"] == "transport"
    assert task.stats["session_id"] == "abc"
    assert task.stats["node"] == "build"


def test_a_failure_reason_outside_05s_list_is_refused() -> None:
    with pytest.raises(ValueError, match="not one of 05"):
        StatsMockAgent(fail="exploded")


async def test_a_scripted_field_the_entry_has_no_room_for_is_refused(
    context: Context,
) -> None:
    with bind(await context()), pytest.raises(ValueError, match="duration_s"):
        await StatsMockAgent(stats={"duration_s": 3}, output=1).run()


# --------------------------------------------------------------------------
# FakeStatsProvider
# --------------------------------------------------------------------------


async def test_the_provider_answers_with_what_it_was_scripted_with() -> None:
    provider = FakeStatsProvider(
        stats={"model": "pi/qwen", "input_tokens": 10, "cost": 1.5},
        stop_reason="length",
    )
    stats = await provider.stats("sess-1", "/work")
    assert stats is not None
    assert (stats.model, stats.input_tokens, stats.cost) == ("pi/qwen", 10, 1.5)
    assert stats.output_tokens is None
    assert await provider.final_stop_reason("sess-1", "/work") == "length"
    assert provider.calls == [("sess-1", "/work"), ("sess-1", "/work")]


async def test_a_provider_that_found_nothing_says_so() -> None:
    """`None` is an answer: not determined, and never a zero."""

    provider = FakeStatsProvider()
    assert await provider.stats("sess-1", None) is None
    assert await provider.final_stop_reason("sess-1", None) is None


async def test_a_session_stats_instance_is_taken_as_it_is() -> None:
    scripted = SessionStats(model="pi/qwen", output_tokens=4)
    provider = FakeStatsProvider(stats=scripted)
    assert await provider.stats("sess-1", None) is scripted
