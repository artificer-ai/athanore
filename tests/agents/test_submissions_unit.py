"""Validate a submission, attach it, and ask for it again (05, 19).

The three helpers T035 adds are the whole of what a façade knows about
structured output, and each one is asserted against a real store: a
submission is a row, "the latest" is an ordering over rows, and a fake
``latest()`` would let this suite agree with itself about which of two
payloads wins.

The repair prompt is asserted the way ``test_prompt.py`` asserts the
rest of 19 — by reading the fenced blocks out of
``docs/v1/19-agent-prompts.md`` at run time and filling in their
stand-in lines. The two modules read different blocks and fill different
stand-ins, so each carries its own reader; what they share is the rule,
which is that the document is the specification and a retyped copy of it
proves nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from pydantic import BaseModel
from structlog.testing import capture_logs

from athanore.agents.base import AgentError, AgentResult
from athanore.agents.submissions import (
    NO_SUBMISSION,
    PAYLOAD_CHARS,
    attach,
    needs_repair,
    repair_prompt,
    validate_submission,
)
from athanore.engine.context import TaskContext

Make = Callable[..., Awaitable[TaskContext]]

#: The specification of the text. Read, not remembered.
DOC = Path(__file__).parents[2] / "docs" / "v1" / "19-agent-prompts.md"

REPAIR = "## Repair turn"
SUBMIT = "## Submission instructions"


class Verdict(BaseModel):
    """The shape a submission must have, for the tests that declare one."""

    verdict: str
    notes: str = ""


# --------------------------------------------------------------------------
# 19, read back out of the document
# --------------------------------------------------------------------------


def block(heading: str, index: int = 0) -> str:
    """The ``index``-th fenced block under ``heading`` in 19."""

    text = DOC.read_text(encoding="utf-8")
    start = text.index(heading) + len(heading)
    blocks = re.findall(r"```\n(.*?)\n```\n", text[start:], re.S)
    assert len(blocks) > index, f"19 has no block {index} under {heading!r}"
    return blocks[index]


def submit_block(ctx: TaskContext, model: type[BaseModel]) -> str:
    """19 §Submission instructions, filled the way 19 defines it."""

    base = f"{ctx.api_base}/api/agent/tasks/{ctx.task_id}"
    text = block(SUBMIT)
    for name, value in (
        ("{base}", base),
        ("{token}", ctx.token),
        ("{schema}", json.dumps(model.model_json_schema(), indent=2)),
    ):
        text = text.replace(name, value)
    return text


def rejected_block(ctx: TaskContext, errors: object, payload: object) -> str:
    """19 §Repair turn, first block: the turn that quotes a 422."""

    return (
        block(REPAIR, 0)
        .replace("{errors as JSON, indent=2}", json.dumps(errors, indent=2))
        .replace(
            "{payload as JSON, first 2000 characters}",
            json.dumps(payload)[:PAYLOAD_CHARS],
        )
        .replace("<submission instructions>", submit_block(ctx, Verdict))
    )


def nothing_block(ctx: TaskContext) -> str:
    """19 §Repair turn, second block: the turn that has nothing to quote."""

    return block(REPAIR, 1).replace(
        "<submission instructions>", submit_block(ctx, Verdict)
    )


def rejection(errors: object, payload: object) -> dict[str, object]:
    """What the submit endpoint records on ``ctx.last_rejection`` (T045)."""

    return {
        "errors": errors,
        "schema": Verdict.model_json_schema(),
        "payload": payload,
    }


MISFIT = [{"loc": ["verdict"], "msg": "Field required", "type": "missing"}]


# --------------------------------------------------------------------------
# validate_submission
# --------------------------------------------------------------------------


def test_no_model_accepts_anything_raw() -> None:
    """05 §Submissions: without an ``output_model``, payloads are raw."""

    payload = {"anything": [1, 2, 3]}

    assert validate_submission(None, payload) == (True, [], payload)


def test_a_fitting_payload_normalises_to_the_model() -> None:
    ok, errors, normalised = validate_submission(Verdict, {"verdict": "ship"})

    assert (ok, errors) == (True, [])
    assert isinstance(normalised, Verdict)
    assert normalised.verdict == "ship"
    assert normalised.notes == ""


def test_a_misfit_reports_18s_three_fields_and_nothing_else() -> None:
    """``input`` is the payload, and the payload travels as the payload."""

    ok, errors, normalised = validate_submission(Verdict, {"notes": "no verdict"})

    assert (ok, normalised) == (False, None)
    assert errors == MISFIT
    assert all(sorted(error) == ["loc", "msg", "type"] for error in errors)


def test_a_payload_that_is_not_an_object_is_a_misfit() -> None:
    ok, errors, _normalised = validate_submission(Verdict, "ship it")

    assert not ok
    assert errors[0]["type"] == "model_type"


# --------------------------------------------------------------------------
# attach
# --------------------------------------------------------------------------


async def test_attach_picks_the_latest_submission(context: Make) -> None:
    """An agent that submitted twice meant the second one (05)."""

    ctx = await context()
    ctx.output_model = Verdict
    await ctx.services.submissions.accept({"verdict": "first"})
    await ctx.services.submissions.accept({"verdict": "second"})

    result = await attach(ctx, AgentResult())

    assert isinstance(result.output, Verdict)
    assert result.output.verdict == "second"


async def test_attach_returns_the_result_it_was_given(context: Make) -> None:
    ctx = await context()
    ctx.output_model = Verdict
    await ctx.services.submissions.accept({"verdict": "ship"})
    result = AgentResult(text="the transcript", stop_reason="end_turn")

    assert await attach(ctx, result) is result
    assert result.text == "the transcript"


async def test_attach_raises_when_nothing_was_submitted(context: Make) -> None:
    ctx = await context()
    ctx.output_model = Verdict

    with pytest.raises(AgentError) as raised:
        await attach(ctx, AgentResult())

    assert str(raised.value) == "agent finished without a valid submission"
    assert str(raised.value) == NO_SUBMISSION


async def test_attach_raises_when_the_latest_no_longer_fits(context: Make) -> None:
    """Stored under one declaration, read under the next one's."""

    ctx = await context()
    await ctx.services.submissions.accept({"note": "no model was declared"})
    ctx.output_model = Verdict

    with capture_logs() as logged:
        with pytest.raises(AgentError, match=NO_SUBMISSION):
            await attach(ctx, AgentResult())

    assert logged[0]["event"] == "no valid submission at the end of the agent run"
    assert logged[0]["log_level"] == "warning"
    assert logged[0]["output_model"] == "Verdict"
    assert logged[0]["errors"] == MISFIT


async def test_attach_without_a_model_takes_the_payload_raw(context: Make) -> None:
    ctx = await context()
    await ctx.services.submissions.accept({"free": "form"})

    result = await attach(ctx, AgentResult())

    assert result.output == {"free": "form"}


async def test_attach_without_a_model_or_a_submission_attaches_nothing(
    context: Make,
) -> None:
    """An agent that was never asked for a shape is not in error."""

    ctx = await context()

    result = await attach(ctx, AgentResult())

    assert result.output is None
    assert result.ok


async def test_attach_outside_a_task_has_nothing_to_attach() -> None:
    """No task, no endpoint to have submitted to (08 §Agent)."""

    result = await attach(None, AgentResult())

    assert result.output is None


# --------------------------------------------------------------------------
# needs_repair
# --------------------------------------------------------------------------


async def test_repair_is_needed_after_an_empty_end_turn(context: Make) -> None:
    ctx = await context()
    ctx.output_model = Verdict

    assert await needs_repair(ctx, "end_turn") is True


async def test_repair_is_not_needed_once_a_valid_submission_exists(
    context: Make,
) -> None:
    ctx = await context()
    ctx.output_model = Verdict
    await ctx.services.submissions.accept({"verdict": "ship"})

    assert await needs_repair(ctx, "end_turn") is False


async def test_repair_is_needed_when_the_submission_does_not_fit(
    context: Make,
) -> None:
    ctx = await context()
    await ctx.services.submissions.accept({"note": "wrong shape"})
    ctx.output_model = Verdict

    assert await needs_repair(ctx, "end_turn") is True


@pytest.mark.parametrize("stop_reason", ["refusal", "cancelled", "max_tokens", None])
async def test_only_an_end_turn_is_worth_repairing(
    context: Make, stop_reason: str | None
) -> None:
    """A refusal or a cut-off turn is an outcome, not a misfiled result."""

    ctx = await context()
    ctx.output_model = Verdict

    assert await needs_repair(ctx, stop_reason) is False


async def test_no_repair_without_a_declared_model(context: Make) -> None:
    ctx = await context()

    assert await needs_repair(ctx, "end_turn") is False


async def test_no_repair_outside_a_task() -> None:
    assert await needs_repair(None, "end_turn") is False


# --------------------------------------------------------------------------
# repair_prompt
# --------------------------------------------------------------------------


async def test_the_repair_turn_quotes_the_last_rejection(context: Make) -> None:
    ctx = await context()
    ctx.output_model = Verdict
    payload = {"notes": "no verdict"}
    ctx.last_rejection = rejection(MISFIT, payload)

    prompt = repair_prompt(ctx, 1)

    assert prompt == rejected_block(ctx, MISFIT, payload)
    assert json.dumps(MISFIT, indent=2) in prompt
    assert json.dumps(payload) in prompt
    assert json.dumps(Verdict.model_json_schema(), indent=2) in prompt
    assert "Do not redo the work." in prompt


async def test_the_repair_turn_says_so_when_nothing_was_submitted(
    context: Make,
) -> None:
    ctx = await context()
    ctx.output_model = Verdict

    prompt = repair_prompt(ctx, 2)

    assert prompt == nothing_block(ctx)
    assert "(nothing was submitted)" in prompt
    assert json.dumps(Verdict.model_json_schema(), indent=2) in prompt


async def test_a_long_rejected_payload_is_truncated(context: Make) -> None:
    ctx = await context()
    ctx.output_model = Verdict
    payload = {"notes": "x" * 4000}
    ctx.last_rejection = rejection(MISFIT, payload)

    prompt = repair_prompt(ctx, 1)

    quoted = json.dumps(payload)
    assert quoted not in prompt
    assert quoted[:PAYLOAD_CHARS] in prompt
    assert quoted[: PAYLOAD_CHARS + 1] not in prompt


async def test_the_quoted_payload_is_text_and_not_a_template(
    context: Make,
) -> None:
    """A single pass: nothing an agent submits can conjure a token (D119)."""

    ctx = await context()
    ctx.output_model = Verdict
    ctx.last_rejection = rejection(MISFIT, {"notes": "{token} {base} {payload}"})

    prompt = repair_prompt(ctx, 1)

    assert "{token} {base} {payload}" in prompt
    header = "X-Athanore-Token: "
    found = [match.start() for match in re.finditer(re.escape(ctx.token), prompt)]
    assert len(found) == 1
    assert prompt[found[0] - len(header) : found[0]] == header


async def test_the_repair_turn_needs_a_declared_model(context: Make) -> None:
    """There is no repair without a shape to repair towards."""

    ctx = await context()

    with pytest.raises(ValueError, match="declared output_model"):
        repair_prompt(ctx, 1)


async def test_repair_turns_are_counted_from_one(context: Make) -> None:
    ctx = await context()
    ctx.output_model = Verdict

    with pytest.raises(ValueError, match="counted from 1"):
        repair_prompt(ctx, 0)
