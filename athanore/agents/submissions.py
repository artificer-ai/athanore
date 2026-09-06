"""What an agent submitted: validate it, attach it, or ask for it again.

05 §Submissions is the rule these three helpers implement — *the latest
valid payload wins, and a declared ``output_model`` is what "valid"
means* — and 19 §Repair turn is, byte for byte, what an agent is told
when there is no such payload.

The split is deliberate. :func:`validate_submission` is the predicate,
and it is the same one the submit endpoint applies (T045): an agent and
an operator are shown the same errors because the same function produced
them. :func:`attach` is the read a finished run makes. :func:`needs_repair`
answers one question — *is another turn worth sending?* — and
:func:`repair_prompt` says what that turn contains. **Neither of the last
two decides anything**: the ACP turn loop (T037, T039) owns
``max_repair_turns``, the ``submission.repair`` event and the transcript
notice. This module has no loop and no state.

Two properties are load-bearing:

**Latest, not first.** ``submissions.latest()`` is ordered by ``id``
descending (07), and an agent that submitted twice meant the second one —
a repair turn is exactly that case, and quoting the rejected payload back
would be pointless if the fix were then ignored.

**The rejected payload is text, never a template.** It is the one string
in a prompt an agent chose the bytes of, so the substitution into 19's
repair block is a single pass: a value that lands in the prompt is never
re-scanned, and a ``{token}`` an agent submitted stays the six characters
it was (D119, 12 §Task tokens).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from athanore.agents.base import AgentError, AgentResult, submission_instructions
from athanore.engine.context import TaskContext
from athanore.logging import get_logger

_log = get_logger(__name__)

__all__ = [
    "attach",
    "needs_repair",
    "repair_prompt",
    "validate_submission",
]

#: How much of a rejected payload 19 quotes back to the agent.
PAYLOAD_CHARS = 2000

#: The message an unusable run ends with. A missing submission and an
#: invalid one are the same outcome for a body — there is no value to
#: route on — so they are the same error, and the validation errors go to
#: the structured log rather than into an exception a body would have to
#: parse (05 §AgentResult).
NO_SUBMISSION = "agent finished without a valid submission"


def validate_submission(
    model: type[BaseModel] | None, payload: Any
) -> tuple[bool, list[dict[str, Any]], Any]:
    """Check ``payload`` against ``model``: ``(ok, errors, normalised)``.

    With no model declared, submissions are stored raw (05 §Submissions):
    everything fits, and ``normalised`` is the payload itself.

    With one, ``normalised`` is the **validated model instance** — what
    ``AgentResult.output`` carries and what a body reads attributes off.
    A caller that needs a row instead (the submit endpoint, storing it)
    dumps it; a caller that needs the payload the agent sent still has it.

    ``errors`` is empty when ``ok``, and otherwise pydantic's errors
    projected onto 18's ``loc``/``msg``/``type`` — the shape
    ``submissions.reject()`` emits, the 422 body carries and
    :func:`repair_prompt` quotes. ``input`` and ``url`` are dropped here
    rather than three layers later: the input is the payload, and it
    travels as the payload (18 §Rules).
    """

    if model is None:
        return True, [], payload
    try:
        return True, [], model.model_validate(payload)
    except PydanticValidationError as exc:
        return False, [_projected(error) for error in exc.errors()], None


def _projected(error: Mapping[str, Any]) -> dict[str, Any]:
    """One pydantic error, as 18 fixes it. ``loc`` is a tuple; JSON has none."""

    return {
        "loc": list(error["loc"]),
        "msg": str(error["msg"]),
        "type": str(error["type"]),
    }


async def attach(ctx: TaskContext | None, result: AgentResult) -> AgentResult:
    """Put this task's latest submission on ``result``, or raise.

    The last step of a run that got as far as an answer (05 §Session
    lifecycle, step 6). With an ``output_model`` declared, a missing or
    invalid submission is an :exc:`AgentError`: the body asked for a
    shape, the agent did not produce it, and there is nothing to route
    on. Without one, whatever was submitted is attached raw, and nothing
    at all is a ``None`` output rather than an error — an agent with no
    declared shape was never required to submit.

    ``ctx`` is optional because an agent may be run outside a node body,
    where there is no task to have submitted anything: the endpoint an
    agent would post to is scoped to a task (08 §Agent). That is a
    missing submission like any other.

    The result is mutated and returned, so a caller may write
    ``return await attach(ctx, result)``.
    """

    ok, errors, value = await _latest(ctx)
    model = ctx.output_model if ctx is not None else None
    if model is None:
        result.output = value
        return result
    if not ok:
        _log.warning(
            "no valid submission at the end of the agent run",
            task_id=None if ctx is None else ctx.task_id,
            output_model=model.__name__,
            errors=errors,
        )
        raise AgentError(NO_SUBMISSION)
    result.output = value
    return result


async def needs_repair(ctx: TaskContext | None, stop_reason: str | None) -> bool:
    """Whether a repair turn is called for (05 §Session lifecycle, step 5).

    Three conditions, all required: the turn ended of its own accord, a
    model was declared, and no valid submission is stored. The first is
    what keeps this off every other exit — a refusal, a cancellation or a
    turn cut off at the token limit is an *outcome*, and asking an agent
    that refused to submit anyway would spend the budget on a turn that
    cannot succeed (the caller returns a failed result instead).

    How many such turns to send is the caller's: ``max_repair_turns``
    lives on :class:`~athanore.agents.acp.ACPAgent`, not here.
    """

    if ctx is None or ctx.output_model is None:
        return False
    if stop_reason != "end_turn":
        return False
    ok, _errors, _value = await _latest(ctx)
    return not ok


def repair_prompt(ctx: TaskContext, turn: int) -> str:
    """19 §Repair turn: the follow-up sent on the same session.

    Two texts, and which one is sent is the difference between an agent
    that missed the instruction and one that tried: with a rejection
    recorded — ``ctx.last_rejection``, set by the submit endpoint from
    what ``submissions.reject()`` returned (T045) — the turn quotes the
    validation errors and the payload they were about, so the agent fixes
    a shape it can see. With none, it says plainly that nothing arrived.
    Both end with the submission instructions and with 19's one
    instruction that matters: *do not redo the work*.

    19's block is rendered **line for line**: each stand-in line — the
    errors, the payload, the submission instructions — becomes its value
    and nothing else moves. That is why the sentence after the payload
    opens on a lone ``.`` and why the instructions follow on the next
    line rather than after a blank one (D120): the document is the text,
    and a rule that reads it as written is the only one a test can check
    against it.

    The schema quoted is ``ctx.output_model``'s — the model the endpoint
    rejected against, which is what the agent has to satisfy next. There
    is no repair turn without one, so a call with no model declared is a
    caller bug and raises.

    ``turn`` is the caller's 1-based repair counter. 19's text does not
    carry it — the turn number belongs to the transcript notice and the
    ``submission.repair`` event, which the loop writes — so it is checked
    here and not rendered: a 0-based caller is a failure at the call
    rather than a silently short repair budget.
    """

    if ctx.output_model is None:
        raise ValueError("repair_prompt needs a declared output_model")
    if turn < 1:
        raise ValueError(f"a repair turn is counted from 1, not {turn}")

    rejection = ctx.last_rejection
    if rejection:
        head = _fill(
            _REPAIR_REJECTED,
            errors=_json(rejection.get("errors", []), indent=2),
            payload=_json(rejection.get("payload"))[:PAYLOAD_CHARS],
        )
    else:
        head = _REPAIR_NOTHING
    return f"{head}\n{submission_instructions(ctx, ctx.output_model)}"


async def _latest(ctx: TaskContext | None) -> tuple[bool, list[dict[str, Any]], Any]:
    """This task's newest submission, validated: ``(ok, errors, value)``.

    ``ok`` is false when there is no submission at all, which is why the
    three-tuple is not simply :func:`validate_submission`'s: "nothing was
    submitted" and "what was submitted does not fit" are one answer to
    the one question both callers ask, and the empty ``errors`` is what
    tells them apart.

    The stored payload is re-validated rather than trusted. Only valid
    payloads are stored (05 §Submissions), but they were validated
    against whatever model was declared *then*, and a body that runs two
    agents in sequence declares a different one for each.
    """

    if ctx is None:
        return False, [], None
    row = await ctx.services.submissions.latest()
    if row is None:
        return False, [], None
    return validate_submission(ctx.output_model, row.payload)


def _json(value: Any, *, indent: int | None = None) -> str:
    """``value`` as JSON, never raising.

    Everything here came off the wire as JSON and re-serialises, but a
    prompt is not the place to discover otherwise: failing to quote a
    payload back would turn a repairable turn into a crashed run.
    """

    return json.dumps(value, indent=indent, default=str)


#: The two substitutions of 19's repair block, and the only ones this
#: module makes. One pass, because both values are the agent's own bytes
#: quoted back at it (D119).
_PLACEHOLDER = re.compile(r"\{(errors|payload)\}")


def _fill(template: str, **values: str) -> str:
    """``template`` with ``{errors}`` and ``{payload}`` filled, in one pass."""

    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


# --------------------------------------------------------------------------
# 19 §Repair turn, verbatim. Compared against the document by the tests.
# --------------------------------------------------------------------------

#: Sent when the last submission was rejected. The lone ``.`` line is 19's.
_REPAIR_REJECTED = (
    "Your turn ended, but no valid structured result was received for "
    "this task — your last submission was rejected with these "
    "validation errors:\n"
    "{errors}\n"
    "Rejected payload:\n"
    "{payload}\n"
    ".\n"
    "Do not redo the work. Fix the result and submit it now."
)

#: Sent when nothing was submitted at all.
_REPAIR_NOTHING = (
    "Your turn ended, but no valid structured result was received for "
    "this task (nothing was submitted).\n"
    "Do not redo the work. Fix the result and submit it now."
)
