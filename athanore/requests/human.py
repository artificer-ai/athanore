"""``human_input``: the one call a node body makes to ask a person.

04 §Waiting is the shape and 06 §Restart durability is the rest of it:

.. code-block:: python

    answer = await human_input("Playtest it. Good to ship?")
    choice = await human_input("Ship it?", options=["approve", "reject"])
    signoff = await human_input("Sign off", output_model=Approval)

Four things happen in that one call, and each is somebody else's code:
the request is opened at this attempt's next ordinal
(``ctx.services.requests``, T032), the attempt's pool slot goes back for
the duration of the wait (``ctx.services.lease.released``, T026), the
answer is validated where it lands rather than here
(:mod:`athanore.requests.validators`, registered on the request), and the
value is decoded into what the mode promised. This module is the seam
between them and holds no state of its own.

**The mode comes from the arguments.** ``options`` asks for a choice and
returns the chosen ``option_id``; ``output_model`` asks for an object and
returns a validated instance of the model; neither asks for text and
returns the string. Passing both is a :exc:`ValueError` rather than a
silent precedence rule — a caller who passed both meant one of them, and
guessing which would be a question answered into the wrong shape.

**Waiting does not hold a worker slot.** The MVP parked the body with its
slot still held, so under ``workers=1`` one playtest question stalled the
whole server. ``released()`` moves the task to ``waiting``, gives the
slot back, and takes one again through the pool's re-admit queue when the
answer arrives — ahead of every ``ready`` task, because this body is
mid-execution and queued once already.

**A crash costs the operator nothing.** The request is numbered by the
attempt, so a body re-executed after a restart re-attaches to the
questions it already asked instead of asking them again: an answered one
is returned without waiting, a pending one is parked on. The one case
that cannot simply replay is a form answer that no longer fits its model
— nothing validated it in the gap between the crash and the re-attach
(06 §Restart durability) — and that is logged, appended to the prompt,
and asked again as a **new** request at the next ordinal. Failing the
body instead would throw away the answers before it; dropping the
mismatch silently would hand the body a value it did not ask for.

``TimeoutError`` propagates: a wait that gave up is not an answer, and
rule 3 makes the node body — not this module — the thing that decides
what a question nobody answered means.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel

from athanore.engine.context import TaskContext, current_task
from athanore.requests.errors import InvalidAnswer
from athanore.requests.validators import ErrorDict, Validator, pydantic_validator
from athanore.store.rows import AnswerRow, LogAuthor, LogKind, RequestKind, RequestMode

#: What an ``options`` argument may hold: an id, or a mapping carrying
#: any of ``option_id``, ``name`` and ``kind`` (06 §The model).
Option = str | Mapping[str, Any]


async def human_input(
    prompt: str,
    *,
    options: Sequence[Option] | None = None,
    output_model: type[BaseModel] | None = None,
    # ASYNC109: the timeout is 04 §Waiting's signature and belongs to the
    # request rather than to this call. A caller cannot wrap it in
    # `asyncio.timeout`: the scope would cancel the body inside the wait
    # and take the released slot with it, where this bounds the *wait* and
    # leaves the attempt running with its slot back to decide what a
    # question nobody answered means.
    timeout: float | None = None,  # noqa: ASYNC109
) -> Any:
    """Ask the operator ``prompt`` and return their answer.

    Returns the chosen ``option_id`` for an ``options`` question, the
    string for a ``text`` one, and a validated ``output_model`` instance
    for a ``form`` one.

    Raises :exc:`ValueError` for arguments that do not name one question —
    both ``options`` and ``output_model``, an empty ``options``, a bare
    string where a list of options belongs, an option with neither an id
    nor a name — ``RuntimeError`` outside a node body,
    and :exc:`TimeoutError` when ``timeout`` elapses with the question
    still open. The request is left pending in that last case: a wait that
    gave up is not an answer, and the operator can still give one.
    """

    ctx = current_task()
    mode = _mode(options, output_model)
    offered = None if options is None else [_option(one) for one in options]
    schema = None if output_model is None else output_model.model_json_schema()
    validator = None if output_model is None else pydantic_validator(output_model)

    ask = prompt
    while True:
        answer = await _answer(ctx, ask, mode, offered, schema, validator, timeout)
        if mode is RequestMode.options:
            # `answer()` refuses an `option_id` the request did not offer,
            # so the column is set for every answer that got this far.
            return answer.option_id
        if validator is None:
            # `text`, the one mode with nothing to validate against: the
            # non-empty string the service already refused anything else for.
            return answer.value
        try:
            return validator(answer.value)
        except InvalidAnswer as exc:
            # The restart gap (06 §Restart durability): this answer was
            # given while no validator was registered, and it no longer
            # fits. Say so where the operator will see it, and ask again
            # with the errors attached.
            await ctx.services.log.append(
                f"the answer to request {answer.request_id} no longer fits "
                f"{_model_name(output_model)}; asking again\n"
                f"{_error_lines(exc.errors)}",
                author=LogAuthor.engine,
                kind=LogKind.note,
            )
            ask = f"{prompt}\n\n{_rejection(exc)}"


async def _answer(
    ctx: TaskContext,
    prompt: str,
    mode: RequestMode,
    options: list[dict[str, Any]] | None,
    schema: dict[str, Any] | None,
    validator: Validator | None,
    timeout: float | None,  # noqa: ASYNC109 - handed to `wait`, which is the wrapper
) -> AnswerRow:
    """One question, asked and answered: the request, the park, the wait.

    The request is this attempt's next ordinal, which is what makes the
    re-executed body ask the question it has not asked yet rather than the
    first one again. An answer already on it is returned **without
    waiting** — a replay is not a second waiter, and parking on a question
    that has been answered would cost the operator a slot release, two
    events and a re-admit for nothing.

    The validator is registered before the park and removed after it on
    every path: one left behind would validate the *next* answer to a
    request this call has stopped caring about, and one registered a
    moment too late is the gap that the re-ask above exists for.
    """

    request = await ctx.services.requests.reopen_or_create(
        prompt, mode=mode, kind=RequestKind.question, options=options, schema=schema
    )
    replayed = await ctx.services.requests.poll(request.id, 0)
    if replayed is not None:
        return replayed
    if validator is not None:
        ctx.services.requests.register_validator(request.id, validator)
    try:
        async with ctx.services.lease.released(request.id):
            return await ctx.services.requests.wait(request.id, timeout)
    finally:
        if validator is not None:
            ctx.services.requests.unregister_validator(request.id)


def _mode(
    options: Sequence[Option] | None, output_model: type[BaseModel] | None
) -> RequestMode:
    """Which of the three questions the arguments name (06 §The model)."""

    if options is not None and output_model is not None:
        raise ValueError(
            "human_input takes `options` or `output_model`, not both: they "
            "are two shapes of answer and the call has one"
        )
    if options is None:
        return RequestMode.text if output_model is None else RequestMode.form
    if isinstance(options, str):
        # A string is a sequence of one-character strings, so this would
        # otherwise be a question offering "y", "e" and "s".
        raise ValueError(
            f"human_input(options={options!r}) is a string, not a list of "
            "options: one option is still a list of one"
        )
    if not options:
        raise ValueError(
            "human_input(options=[]) offers nothing to choose from, and an "
            "answer to it could never be one of the options it listed"
        )
    return RequestMode.options


def _option(option: Option) -> dict[str, Any]:
    """One entry of ``options``, normalised to ``{option_id, name, kind}``.

    A string is all three: the id is what the body gets back and the name
    is what the operator reads, so ``"approve"`` is a complete option. A
    mapping may name them separately, and may carry the ``kind`` the SPA
    styles the button by (``allow_*`` accent, ``reject_*`` destructive) —
    ``None`` for the questions that are not permissions, which is most of
    them.

    Anything else, and a mapping with neither an id nor a name, is a
    :exc:`ValueError`: an option the operator cannot see or the body
    cannot receive is not an option.
    """

    if isinstance(option, str):
        return {"option_id": option, "name": option, "kind": None}
    if not isinstance(option, Mapping):
        raise ValueError(
            f"an option is a string or a mapping, not {type(option).__name__}"
        )
    option_id = option.get("option_id") or option.get("name")
    if not isinstance(option_id, str) or not option_id:
        raise ValueError(
            f"the option {dict(option)!r} has no `option_id` and no `name`: "
            "one of them is the id the body is answered with"
        )
    name = option.get("name") or option_id
    return {"option_id": option_id, "name": name, "kind": option.get("kind")}


def _model_name(output_model: type[BaseModel] | None) -> str:
    """The model's name for a log line. ``form`` always has one."""

    return "the requested schema" if output_model is None else output_model.__name__


def _rejection(exc: InvalidAnswer) -> str:
    """The paragraph appended to the prompt when an answer is re-asked.

    The operator reads the question, not the log, so the errors go where
    the question is: the new request at the next ordinal carries the
    prompt *and* what was wrong with the answer to the last one.
    """

    return f"(the previous answer was rejected:\n{_error_lines(exc.errors)})"


def _error_lines(errors: list[ErrorDict]) -> str:
    """``[{loc, msg, type}]`` as one line each, for a person to read."""

    return (
        "\n".join(
            f"- {_where(error.get('loc'))}: {error.get('msg', 'invalid')}"
            for error in errors
        )
        or "- the answer does not fit the model"
    )


def _where(loc: Any) -> str:
    """One error's ``loc`` as a dotted path, or the whole answer."""

    if not isinstance(loc, tuple | list) or not loc:
        return "the answer"
    return ".".join(str(part) for part in loc)


__all__ = ["human_input"]
