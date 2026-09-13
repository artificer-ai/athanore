"""The prompt an agent is handed (19, normative; 05 §Prompt assembly).

Two things are being asserted and they pull in opposite directions.

**The blocks are the document's, byte for byte.** 19 is normative because
the text is behaviour: the example workflows were tuned against it and
``FakeACPAgent`` parses it, so a reworded line is a broken test agent and
a differently-behaved model. The expectations here are therefore read out
of ``docs/v1/19-agent-prompts.md`` at run time and filled in, rather than
retyped — a copy of a copy asserts only that someone copied it twice.

**The token is in a header and nowhere else.** A token in a URL ends up in
an access log, a shell history and a proxy trace, and the prompt is the
one place in the package that writes one into text at all (12 §Task
tokens). The check is over the whole rendered prompt, not over the block
that was supposed to carry it: it is the absence that matters, so looking
only where it was expected would prove nothing.

Ported from the MVP's ``tests/test_agents.py`` prompt assertions. Its
`template=` cases are gone with the feature (05).
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from pydantic import BaseModel
from structlog.testing import capture_logs

from athanore.agents.base import Agent, AgentError, AgentResult, tier_block
from athanore.engine.context import TaskContext

Make = Callable[..., Awaitable[TaskContext]]

#: The specification of the text. Read, not remembered.
DOC = Path(__file__).parents[2] / "docs" / "v1" / "19-agent-prompts.md"

SYSTEM = "# Role\n\nYou are the test stage."
ASSIGNMENT = "do the thing"
TITLE = "ship the widget"


class Verdict(BaseModel):
    """The shape a submission must have, for the agents that declare one."""

    verdict: str
    notes: str = ""


class Plain(Agent):
    system_prompt = SYSTEM


class Asking(Plain):
    ask_policy = "http"


class Structured(Plain):
    output_model = Verdict


class Everything(Plain):
    ask_policy = "http"
    output_model = Verdict


# --------------------------------------------------------------------------
# 19, read back out of the document
# --------------------------------------------------------------------------


def block(heading: str) -> str:
    """The first fenced block under ``heading`` in 19."""

    text = DOC.read_text(encoding="utf-8")
    start = text.index(heading) + len(heading)
    found = re.search(r"```\n(.*?)\n```\n", text[start:], re.S)
    assert found is not None, f"19 has no block under {heading!r}"
    return found.group(1)


def fill(text: str, ctx: TaskContext, *, title: str = "", schema: str = "") -> str:
    """19's placeholders, substituted the way 19 defines them."""

    base = f"{ctx.api_base}/api/agent/tasks/{ctx.task_id}"
    for name, value in (
        ("{base}", base),
        ("{token}", ctx.token),
        ("{task_id}", str(ctx.task_id)),
        ("{title}", title),
        ("{node}", ctx.node),
        ("{workflow}", ctx.workflow),
        ("{run_id}", ctx.run_id),
        ("{schema}", schema),
    ):
        text = text.replace(name, value)
    return text


def kickoff(ctx: TaskContext, title: str = "") -> str:
    return fill(block("## Kickoff (tool-agnostic core)"), ctx, title=title)


def http_block(ctx: TaskContext) -> str:
    return fill(block("### Tier block: `http`"), ctx)


def ask_block(ctx: TaskContext) -> str:
    return fill(block("## Ask instructions"), ctx)


def submit_block(ctx: TaskContext, model: type[BaseModel]) -> str:
    schema = json.dumps(model.model_json_schema(), indent=2)
    return fill(block("## Submission instructions"), ctx, schema=schema)


def quoted(title: str) -> str:
    """``{title}``: the run's title, as 19 spells it into the kickoff."""

    return f' "{title}"'


# --------------------------------------------------------------------------
# Assembly: which sections, and their separators
# --------------------------------------------------------------------------


async def test_the_assignment_is_sent_alone_without_a_system_prompt() -> None:
    """19 §Assembly: no heading and no separator for a bare assignment."""

    assert await Agent().render_prompt(ASSIGNMENT) == ASSIGNMENT


async def test_a_system_prompt_precedes_the_assignment() -> None:
    prompt = await Plain().render_prompt(ASSIGNMENT)

    assert prompt == f"{SYSTEM}\n\n---\n\n## Your assignment\n\n{ASSIGNMENT}"


async def test_the_assignment_section_is_omitted_with_its_separator() -> None:
    """An agent run with no assignment is its system prompt and its task."""

    assert await Plain().render_prompt() == SYSTEM


async def test_the_system_prompt_is_stripped() -> None:
    class Padded(Agent):
        system_prompt = f"\n\n{SYSTEM}\n\n"

    assert await Padded().render_prompt() == SYSTEM


async def test_the_task_section_is_omitted_outside_a_task_context() -> None:
    """No context, no task: the sections that name one cannot be written."""

    with capture_logs() as logged:
        prompt = await Everything().render_prompt(ASSIGNMENT)

    assert "## Your task" not in prompt
    assert "curl" not in prompt
    assert [entry["log_level"] for entry in logged] == ["warning"]
    assert logged[0]["event"] == "agent prompt rendered outside a task context"
    assert logged[0]["agent"] == "Everything"


async def test_a_task_context_is_not_warned_about(context: Make) -> None:
    ctx = await context()

    with capture_logs() as logged:
        await Plain().render_prompt(ASSIGNMENT, ctx)

    assert logged == []


async def test_the_none_tier_is_the_system_prompt_and_the_assignment(
    context: Make,
) -> None:
    """05 §Tooling tiers, 19 §Assembly: on ``none`` the task sections are
    omitted as they are outside a task context — with a task to name.

    ``Everything`` has the most to omit: a tier block, an ask block and a
    submission block. The whole text is asserted, not a substring, so a
    stray separator would fail it too.
    """

    ctx = await context(TITLE)

    prompt = await Everything().render_prompt(ASSIGNMENT, ctx, tier="none")

    assert prompt == "\n\n".join([SYSTEM, "---", f"## Your assignment\n\n{ASSIGNMENT}"])
    assert "## Your task" not in prompt
    assert "curl" not in prompt
    assert ctx.token not in prompt
    assert "submit" not in prompt
    assert "ask" not in prompt.lower()


async def test_the_none_tier_without_a_system_prompt_is_the_assignment_alone(
    context: Make,
) -> None:
    class Bare(Agent):
        output_model = Verdict

    ctx = await context()

    assert await Bare().render_prompt(ASSIGNMENT, ctx, tier="none") == ASSIGNMENT


async def test_the_none_tier_is_not_warned_about(context: Make) -> None:
    """The outside-a-task warning does not fire on ``none``, with a task or
    without one: the absence of the task sections was asked for (D271).
    """

    ctx = await context()

    with capture_logs() as logged:
        await Everything().render_prompt(ASSIGNMENT, ctx, tier="none")
    assert logged == []

    with capture_logs() as logged:
        await Everything().render_prompt(ASSIGNMENT, tier="none")
    assert logged == []


async def test_the_none_tier_has_no_tier_block(context: Make) -> None:
    """``render_prompt`` never reaches the block on ``none``; a caller that
    asks for one anyway has a bug, and gets told rather than a tool list.
    """

    ctx = await context()

    with pytest.raises(ValueError, match="the none tier has no tier block"):
        tier_block(ctx, "none", ask=False)


# --------------------------------------------------------------------------
# The blocks, against 19
# --------------------------------------------------------------------------


async def test_the_task_section_is_19s_kickoff_and_http_tier(context: Make) -> None:
    ctx = await context(TITLE)

    prompt = await Plain().render_prompt(ASSIGNMENT, ctx)

    assert prompt == "\n\n".join(
        [
            SYSTEM,
            "---",
            f"## Your assignment\n\n{ASSIGNMENT}",
            "---",
            kickoff(ctx, quoted(TITLE)),
            http_block(ctx),
        ]
    )


async def test_the_kickoff_carries_the_runs_title(context: Make) -> None:
    ctx = await context(TITLE)

    prompt = await Plain().render_prompt(ctx=ctx)

    assert f'Work on task {ctx.task_id} "{TITLE}" — stage "{ctx.node}"' in prompt
    assert f'of workflow "{ctx.workflow}" (run {ctx.run_id}).' in prompt


async def test_an_untitled_run_contributes_nothing(context: Make) -> None:
    """``{title}`` is empty rather than an empty pair of quotes."""

    ctx = await context("")

    prompt = await Plain().render_prompt(ctx=ctx)

    assert f"Work on task {ctx.task_id} — stage" in prompt
    assert '""' not in prompt


async def test_the_ask_block_is_absent_unless_the_policy_is_http(
    context: Make,
) -> None:
    ctx = await context()

    assert ask_block(ctx) not in await Plain().render_prompt(ctx=ctx)
    assert "/ask" not in await Plain().render_prompt(ctx=ctx)


async def test_the_ask_block_follows_the_tier_block(context: Make) -> None:
    ctx = await context(TITLE)

    prompt = await Asking().render_prompt(ctx=ctx)

    assert prompt == "\n\n".join(
        [
            SYSTEM,
            "---",
            kickoff(ctx, quoted(TITLE)),
            http_block(ctx),
            ask_block(ctx),
        ]
    )


async def test_the_submission_block_is_absent_without_an_output_model(
    context: Make,
) -> None:
    ctx = await context()

    assert "/submit" not in await Plain().render_prompt(ctx=ctx)


async def test_the_submission_block_carries_the_models_schema(
    context: Make,
) -> None:
    ctx = await context(TITLE)

    prompt = await Structured().render_prompt(ctx=ctx)

    assert prompt == "\n\n".join(
        [
            SYSTEM,
            "---",
            kickoff(ctx, quoted(TITLE)),
            http_block(ctx),
            submit_block(ctx, Verdict),
        ]
    )
    assert json.dumps(Verdict.model_json_schema(), indent=2) in prompt


async def test_every_section_at_once_is_in_19s_order(context: Make) -> None:
    ctx = await context(TITLE)

    prompt = await Everything().render_prompt(ASSIGNMENT, ctx)

    assert prompt == "\n\n".join(
        [
            SYSTEM,
            "---",
            f"## Your assignment\n\n{ASSIGNMENT}",
            "---",
            kickoff(ctx, quoted(TITLE)),
            http_block(ctx),
            ask_block(ctx),
            submit_block(ctx, Verdict),
        ]
    )


async def test_the_paths_are_the_agent_api(context: Make) -> None:
    """08: everything an agent may call lives under ``/api/agent/``."""

    ctx = await context()

    prompt = await Everything().render_prompt(ctx=ctx)

    base = f"{ctx.api_base}/api/agent/tasks/{ctx.task_id}"
    assert prompt.count(base) == 5
    assert f"{ctx.api_base}/api/tasks/" not in prompt


# --------------------------------------------------------------------------
# The token
# --------------------------------------------------------------------------


async def test_the_token_appears_only_in_a_header(context: Make) -> None:
    """12 §Task tokens: never a query parameter, never a body field."""

    ctx = await context(TITLE)

    prompt = await Everything().render_prompt(ASSIGNMENT, ctx)

    header = "X-Athanore-Token: "
    found = [match.start() for match in re.finditer(re.escape(ctx.token), prompt)]
    assert len(found) == 5
    for at in found:
        assert prompt[at - len(header) : at] == header
    assert "?token=" not in prompt
    assert "_token" not in prompt
    assert "token=" not in prompt


async def test_a_prompt_with_no_task_carries_no_token(context: Make) -> None:
    ctx = await context()

    prompt = await Everything().render_prompt(f"the token is not {ASSIGNMENT}")

    assert ctx.token not in prompt


# --------------------------------------------------------------------------
# Declaration, and the class itself
# --------------------------------------------------------------------------


async def test_declare_publishes_the_agents_configuration(context: Make) -> None:
    """The API reads the task, not the object that spawned the agent."""

    ctx = await context()

    async with Everything().declare(ctx):
        assert ctx.output_model is Verdict
        assert ctx.ask_policy == "http"


async def test_declare_restores_what_it_found(context: Make) -> None:
    ctx = await context()
    ctx.output_model = None
    ctx.ask_policy = "off"

    async with Structured().declare(ctx):
        pass

    assert ctx.output_model is None
    assert ctx.ask_policy == "off"


async def test_declare_nests(context: Make) -> None:
    """A body running one agent inside another's context (05 §Lifecycle)."""

    ctx = await context()

    async with Structured().declare(ctx):
        async with Asking().declare(ctx):
            assert ctx.output_model is None
            assert ctx.ask_policy == "http"
        assert ctx.output_model is Verdict
        assert ctx.ask_policy == "off"

    assert ctx.output_model is None
    assert ctx.ask_policy == "off"


async def test_declare_clears_the_last_rejection_and_puts_it_back(
    context: Make,
) -> None:
    """A repair turn quotes this run's 422, never an earlier agent's."""

    ctx = await context()
    earlier = {"errors": [], "payload": {}}
    ctx.last_rejection = earlier

    async with Structured().declare(ctx):
        assert ctx.last_rejection is None
        ctx.last_rejection = {"errors": [{"loc": ["verdict"]}], "payload": {}}

    assert ctx.last_rejection is earlier


async def test_declare_restores_after_a_failure(context: Make) -> None:
    ctx = await context()

    with pytest.raises(AgentError):
        async with Structured().declare(ctx):
            raise AgentError("the agent never submitted")

    assert ctx.output_model is None


async def test_declare_outside_a_task_context_is_a_no_op() -> None:
    async with Everything().declare(None):
        pass


async def test_the_base_class_has_no_run() -> None:
    with pytest.raises(NotImplementedError, match="Plain has no run"):
        await Plain().run()


def test_a_result_is_ok_only_when_it_completed() -> None:
    assert AgentResult().ok
    assert AgentResult(status="complete", output=Verdict(verdict="ship")).ok
    assert not AgentResult(status="failed", error="refusal").ok
    assert AgentResult().stats == {}
