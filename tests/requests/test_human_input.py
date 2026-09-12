"""``human_input``: the three modes, the released slot, the timeout (T033).

The subject is the one call a node body makes to ask a person (04
§Waiting, 06 §``human_input``), and every test here runs it inside a real
attempt on a pool with one worker, because most of what the call does is
only observable there.

- **The mode comes from the arguments.** ``options`` returns the chosen
  id, ``output_model`` returns a validated instance, neither returns the
  string. What the body gets back is the whole contract of the call.
- **The answer is validated where it lands.** A form answer that does not
  fit the model is refused to the operator who gave it — 422 at the
  endpoint T044a mounts over this — rather than reaching the body as a
  value it did not ask for. The refusal is
  :exc:`~athanore.requests.errors.InvalidAnswer` here because that
  endpoint does not exist yet; the errors it carries are what the form
  renders.
- **Waiting does not hold a worker slot.** This is the MVP's failure
  inverted into an assertion: under ``workers=1`` a second run's task
  must start and finish while the first body is parked, and when the
  answer arrives the parked body must go ahead of a task that became
  ready while it waited. If that test ever passes because the pool had
  two slots, it is asserting nothing.
- **A timeout reaches the body.** It is not an answer and not a failure:
  the exception lands in the body, which decides (rule 3), and the
  question is left open for the operator who was slow.

The replay half of the durability story — a body re-executed after a
crash — is ``test_human_input_replay.py`` (T033a).
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from athanore.events.names import EventName
from athanore.requests.errors import InvalidAnswer, StaleRequest
from athanore.requests.human import human_input
from athanore.requests.service import RequestService
from athanore.store.rows import RequestKind, RequestMode, RequestSource
from athanore.store.uow import Store


class Approval(BaseModel):
    """The shape a ``form`` question asks for."""

    approved: bool
    note: str = ""


# --------------------------------------------------------------------------
# The three modes
# --------------------------------------------------------------------------


async def test_options_returns_the_chosen_id(fleet, service: RequestService) -> None:
    """`options` is a choice, and the body is handed the id it named.

    The strings are normalised into the ``{option_id, name, kind}`` the
    model fixes (06 §The model), because that is what the SPA renders a
    button from and what ``answer`` checks an ``option_id`` against.
    """

    got: list[Any] = []

    async def body() -> str:
        got.append(await human_input("Ship it?", options=["approve", "reject"]))
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    request = await one.only_asked(run_id)
    assert request.mode is RequestMode.options
    assert request.source is RequestSource.node
    assert request.kind is RequestKind.question
    assert request.ordinal == 1
    assert request.prompt == "Ship it?"
    assert request.options == [
        {"option_id": "approve", "name": "approve", "kind": None},
        {"option_id": "reject", "name": "reject", "kind": None},
    ]

    await service.answer(request.id, option_id="reject")
    assert await one.finished(run_id) == "asked"
    assert got == ["reject"]


async def test_an_option_may_name_itself_and_its_kind(
    fleet, service: RequestService
) -> None:
    """A mapping carries the label and the button style an id does not.

    ``kind`` is what the SPA colours by (``allow_*`` accent, ``reject_*``
    destructive, 06 §Surfaces), and a mapping with only a ``name`` is an
    option whose label is its id.
    """

    got: list[Any] = []

    async def body() -> str:
        got.append(
            await human_input(
                "May I?",
                options=[
                    {"option_id": "allow", "name": "Allow once", "kind": "allow_once"},
                    {"name": "Deny"},
                ],
            )
        )
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    request = await one.only_asked(run_id)
    assert request.options == [
        {"option_id": "allow", "name": "Allow once", "kind": "allow_once"},
        {"option_id": "Deny", "name": "Deny", "kind": None},
    ]

    await service.answer(request.id, option_id="Deny")
    await one.finished(run_id)
    assert got == ["Deny"]


async def test_text_returns_the_string(fleet, service: RequestService) -> None:
    """No argument beyond the prompt: a question, and the answer to it."""

    got: list[Any] = []

    async def body() -> str:
        got.append(await human_input("What shall I build?"))
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    request = await one.only_asked(run_id)
    assert request.mode is RequestMode.text
    assert request.options is None and request.schema_ is None

    await service.answer(request.id, value="a bridge")
    await one.finished(run_id)
    assert got == ["a bridge"]


async def test_output_model_returns_an_instance(fleet, service: RequestService) -> None:
    """`form` carries the model's schema out and its instance back.

    The row holds the answer as JSON — ``answers.value`` is a JSON column
    (D115) — and the body is handed the model, which is what the call
    promised: the decode on the way out is what makes those two the same
    thing.
    """

    got: list[Any] = []

    async def body() -> str:
        got.append(await human_input("Sign off", output_model=Approval))
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    request = await one.only_asked(run_id)
    assert request.mode is RequestMode.form
    assert request.schema_ == Approval.model_json_schema()

    await service.answer(request.id, value={"approved": True, "note": "ship it"})
    await one.finished(run_id)
    assert got == [Approval(approved=True, note="ship it")]
    assert isinstance(got[0], Approval)


async def test_arguments_that_name_no_one_question_are_refused(fleet) -> None:
    """Two shapes of answer, or none at all: a ``ValueError``, not a rank.

    The body sees it and nothing is opened — a question the caller did
    not mean is worse than no question at all. The last of the four is
    the one a type checker does not catch: a string *is* a sequence, so
    ``options="yes"`` would otherwise offer "y", "e" and "s".
    """

    raised: list[Exception] = []

    async def body() -> str:
        for call in (
            lambda: human_input("?", options=["a"], output_model=Approval),
            lambda: human_input("?", options=[]),
            lambda: human_input("?", options=[{"kind": "allow_once"}]),
            lambda: human_input("?", options="yes"),
        ):
            try:
                await call()
            except ValueError as exc:
                raised.append(exc)
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    assert await one.finished(run_id) == "asked"
    assert len(raised) == 4
    assert "not both" in str(raised[0])
    assert not await one.requests_of(run_id)


# --------------------------------------------------------------------------
# Validation lands on the answer, not in the body
# --------------------------------------------------------------------------


async def test_a_misfitting_form_answer_is_refused_where_it_lands(
    fleet, service: RequestService
) -> None:
    """The validator ``human_input`` registered runs at the answer (06).

    ``InvalidAnswer`` is the 422 the endpoint returns (08 §Conventions);
    its ``errors`` are pydantic's, which is what the form renders next to
    the field. The body never sees the misfit: it is still parked, and
    the answer that does fit reaches it.
    """

    got: list[Any] = []

    async def body() -> str:
        got.append(await human_input("Sign off", output_model=Approval))
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()
    request = await one.only_asked(run_id)

    with pytest.raises(InvalidAnswer) as refused:
        await service.answer(request.id, value={"approved": "perhaps"})
    assert [error["loc"] for error in refused.value.errors] == [("approved",)]
    assert not got, "a refused answer must not reach the body"

    # The request is still open, and the answer that fits gets through.
    view = await service.view(request.id)
    assert view.answered_by is None
    await service.answer(request.id, value={"approved": False})
    await one.finished(run_id)
    assert got == [Approval(approved=False, note="")]


async def test_the_validator_does_not_outlive_the_call(
    fleet, service: RequestService, wait_for
) -> None:
    """Unregistered on the way out, so it cannot refuse the next answer.

    The body times out and goes on running, leaving the question open. A
    validator left registered would still be refusing answers to it on
    behalf of a call that has stopped waiting — here the object that
    ``Approval`` rejects is stored, because with no validator the shape of
    a ``form`` answer is the whole contract (06 §Service).
    """

    timed_out = asyncio.Event()
    go_on = asyncio.Event()

    async def body() -> str:
        try:
            await human_input("Sign off", output_model=Approval, timeout=0.05)
        except TimeoutError:
            timed_out.set()
        await go_on.wait()
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    request = await one.only_asked(run_id)
    await wait_for(timed_out)

    answer = await service.answer(request.id, value={"approved": "perhaps"})
    assert answer.value == {"approved": "perhaps"}

    go_on.set()
    assert await one.finished(run_id) == "asked"


# --------------------------------------------------------------------------
# The timeout
# --------------------------------------------------------------------------


async def test_a_timeout_raises_in_the_body(
    fleet, service: RequestService, wait_until
) -> None:
    """`timeout=0.1` with nobody answering: the body decides what it means.

    And the question is left **pending**: a wait that gave up is not an
    answer, and the operator who was slow can still give one — until the
    task ends and the request goes stale, which is what the last
    assertion is.
    """

    raised: list[Exception] = []

    async def body() -> str:
        try:
            await human_input("Good to ship?", timeout=0.1)
        except TimeoutError as exc:
            raised.append(exc)
            return "nobody answered"
        return "answered"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()
    request = await one.only_asked(run_id)

    assert await one.finished(run_id) == "nobody answered"
    assert raised and isinstance(raised[0], TimeoutError)

    # The slot came back even though the wait failed: the attempt went on
    # to record an outcome, and the runner records that as a running task.
    # The wait is the runner's `finally`, which is after the row it just
    # read — the run ends in a transaction, the lease goes back after it.
    await wait_until(one.idle)
    with pytest.raises(StaleRequest):
        await service.answer(request.id, value="too late")


# --------------------------------------------------------------------------
# The slot
# --------------------------------------------------------------------------


async def test_a_parked_body_gives_its_slot_up_and_takes_it_back_first(
    fleet, service: RequestService, store: Store, wait_for, wait_until
) -> None:
    """The point of T026 and T033 together, under ``workers=1``.

    Four runs, one worker. The first parks on a question and its slot goes
    back, so the second runs to completion inside that window — the MVP
    stalled here. Then the answer arrives while a third run holds the
    slot, and a fourth is made ready behind it: when the slot comes free
    it goes to the **answered body**, because that body is mid-execution
    and queued once already (04 §Waiting).

    The pool has exactly one slot, which is what makes the ordering mean
    anything: with two, these assertions would pass without the re-admit
    queue existing at all.
    """

    order: list[str] = []
    holding = asyncio.Event()
    let_go = asyncio.Event()
    last_ran = asyncio.Event()

    async def asks() -> str:
        order.append("asks")
        answer = await human_input("Good to ship?")
        order.append(f"asks-resumed:{answer}")
        return answer

    async def quick() -> str:
        order.append("quick")
        return "done"

    async def holds() -> str:
        order.append("holds")
        holding.set()
        await let_go.wait()
        return "done"

    async def last() -> str:
        order.append("last")
        last_ran.set()
        return "done"

    one = fleet({"test": 1})
    for name, node in (
        ("asks", asks),
        ("quick", quick),
        ("holds", holds),
        ("last", last),
    ):
        one.register_body(name, node)

    asking = await one.submit("asks")
    await one.scheduler.start()
    request = await one.only_asked(asking)

    # The parked body is `waiting` and holds nothing. Both, in that
    # order: `released()` writes the status *before* it frees the slot,
    # so that a task another attempt starts against cannot find this one
    # still `in_progress` (04 §Waiting).
    await wait_until(lambda: one.parked(asking))
    await wait_until(one.idle)
    (waiting,) = await one.events_named(asking, EventName.task_waiting)
    assert waiting.data["request_id"] == request.id

    # ...so the run behind it takes the one slot and finishes.
    quickly = await one.submit("quick")
    await wait_until(lambda: one.is_completed(quickly))
    assert order == ["asks", "quick"]
    assert await one.parked(asking)

    # Now the answer arrives while a third run holds the slot, and a
    # fourth becomes ready only once the waiter is in the queue.
    holding_run = await one.submit("holds")
    await wait_for(holding)
    await service.answer(request.id, value="yes")
    await wait_until(lambda: one.queued())
    lastly = await one.submit("last")
    await asyncio.sleep(one.scheduler.tick * 2)  # ticks with no slot free
    assert not last_ran.is_set()

    let_go.set()
    await wait_until(lambda: one.is_completed(asking))
    # `last` may already have run by now — the slot the answered body gave
    # back is legitimately its next — so what is asserted is the order,
    # not the moment: nothing ready overtook the body that was queued.
    resumed_at = order.index("asks-resumed:yes")
    assert "last" not in order[:resumed_at], (
        "a ready task overtook a body already running"
    )

    await wait_until(lambda: one.is_completed(lastly))
    assert order == ["asks", "quick", "holds", "asks-resumed:yes", "last"]
    assert await one.is_completed(holding_run)

    (resumed,) = await one.events_named(asking, EventName.task_resumed)
    assert resumed.data["request_id"] == request.id
    await wait_until(one.idle)

    # The waiter claimed its answer: `human_input` is the one waiter the
    # request was opened for (06 §The model).
    async with store.reader() as reader:
        answer = await reader.requests.get_answer(request.id)
    assert answer is not None and answer.consumed is True
