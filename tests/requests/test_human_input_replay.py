"""``human_input`` after a crash: the answers already given are not re-asked.

T033a, 06 §Restart durability, D44. The durability story of the engine is
"re-execute the attempt", and a body that asks a person three questions
would make that story cost the operator three questions every time the
server was restarted. The ordinal on a node-raised request is what stops
it: the *n*-th ``human_input`` of an attempt is request *n* of that task
row, so a re-executed body re-attaches instead of re-asking.

Three behaviours, one per test:

- **An answered request replays, a pending one is parked on.** The body
  that died after two answers comes back and asks question three — and
  only question three. Nothing it already asked is opened twice, and
  nothing it already asked is *waited on* twice, which is the assertion
  that would fail if replay were implemented as "wait, and hope the
  answer is already there".
- **Each mode replays as its own shape.** ``options`` hands the body the
  ``option_id`` it chose and ``form`` hands it a validated
  ``output_model`` instance, on the replay path as on the live one. The
  two are worth their own tests because the replay reads the answer with
  ``poll`` where a live wait reads it with ``wait``, and because a
  ``form`` answer given while nothing was validating is stored exactly as
  it arrived (D115) — so the validator that turns it into the model runs
  here, on the way out, or nowhere.
- **A replayed answer that no longer fits is re-asked, not dropped.**
  Nothing validated the answer given in the gap between the crash and the
  re-attach (no validator survives a restart, 06 §Restart durability), so
  the misfit is discovered here. It is logged, appended to the prompt,
  and asked again as a **new** request at the next ordinal: failing the
  body would throw away the answers before it, and handing the value over
  would give the body something it did not ask for.
- **A retry asks afresh.** A retry is a new task row, so its ordinals
  start at 1. That is intended and not an oversight: the answers of a
  failed attempt may have been the reason it failed.

The crash is a cancelled attempt and a ``reset_for_recovery`` — which is
what a killed process and a restart are, minus the process (04 §Shutdown,
§Recovery).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from athanore.engine.context import current_task
from athanore.events.names import EventName
from athanore.requests.human import human_input
from athanore.requests.service import RequestService
from athanore.store.rows import RequestRow


class Approval(BaseModel):
    """The shape the third question asks for."""

    approved: bool
    note: str = ""


async def kill(one: Any, task_id: int, wait_until: Any) -> None:
    """The process dies: the attempt goes away and records nothing.

    A cancelled attempt leaves its row untouched (04 §Shutdown), so the
    task stays ``waiting`` on the question it parked on — which is the
    state a killed server leaves behind, and the state in which an
    operator can still answer it.
    """

    assert one.scheduler.cancel_attempts([task_id]) == [task_id]
    await wait_until(one.idle)


async def restart(one: Any, task_id: int) -> None:
    """The server comes back: recovery returns the row to ``ready``.

    ``reset_for_recovery`` is what startup does to the rows an attempt
    was in the middle of; the notify is the dispatch loop noticing.
    """

    assert await one.recover() == [task_id]
    one.notify()


# --------------------------------------------------------------------------
# Replay
# --------------------------------------------------------------------------


async def test_the_re_executed_body_asks_only_what_it_had_not_asked(
    fleet, service: RequestService, wait_until
) -> None:
    """Three questions, a crash after two answers, and one question left.

    The body re-runs from the top: questions one and two return the
    answers already given, without opening a request and without parking,
    and question three is the request the crash left pending — re-attached
    to, not re-created.
    """

    passes: list[list[Any]] = []

    async def body() -> list[Any]:
        got: list[Any] = []
        passes.append(got)
        for prompt in ("one?", "two?", "three?"):
            got.append(await human_input(prompt))
        return got

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    # Two answers, and then the process dies with the body parked on the
    # third question.
    first = await one.only_asked(run_id)
    await service.answer(first.id, value="a bridge")
    (_, second) = await one.asked(run_id, 2)
    await service.answer(second.id, value="in stone")
    (_, _, third) = await one.asked(run_id, 3)
    await wait_until(lambda: one.parked(run_id))
    task_id = (await one.only_task(run_id)).id
    await kill(one, task_id, wait_until)
    await restart(one, task_id)

    # The re-executed body parks on the third question again — the same
    # request, at the same ordinal.
    await wait_until(lambda: one.parked(run_id))
    await service.answer(third.id, value="by June")
    assert await one.finished(run_id) == ["a bridge", "in stone", "by June"]

    assert len(passes) == 2
    assert passes[0] == ["a bridge", "in stone"]

    rows = await one.requests_of(run_id)
    assert [row.ordinal for row in rows] == [1, 2, 3]
    assert [row.prompt for row in rows] == ["one?", "two?", "three?"]
    assert [row.id for row in rows] == [first.id, second.id, third.id]
    assert {row.task_id for row in rows} == {task_id}

    # Three questions were opened, not five, and only the unanswered one
    # was ever parked on — twice, once per attempt of it.
    opened = await one.events_named(run_id, EventName.request_opened)
    assert [event.data["ordinal"] for event in opened] == [1, 2, 3]
    waiting = await one.events_named(run_id, EventName.task_waiting)
    assert [event.data["request_id"] for event in waiting] == [
        first.id,
        second.id,
        third.id,
        third.id,
    ]


async def test_a_replayed_options_answer_gives_the_body_the_id_it_chose(
    fleet, service: RequestService, wait_until
) -> None:
    """An ``options`` question answered in the gap replays as its ``option_id``.

    The answer to an ``options`` request lives in ``answers.option_id``
    and not in ``answers.value``, and the replay reads it through
    ``poll`` — a plain select — where a live wait reads it through the
    update that claims it. Nothing but this asserts that the two agree,
    and a replay that handed the body ``None`` would look exactly like an
    operator who chose nothing.
    """

    passes: list[list[Any]] = []

    async def body() -> str:
        got: list[Any] = []
        passes.append(got)
        got.append(await human_input("what shall I build?"))
        got.append(await human_input("ship it?", options=["approve", "reject"]))
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    first = await one.only_asked(run_id)
    await service.answer(first.id, value="a bridge")
    (_, second) = await one.asked(run_id, 2)
    await wait_until(lambda: one.parked(run_id))
    task_id = (await one.only_task(run_id)).id
    await kill(one, task_id, wait_until)

    # Chosen in the gap, and never claimed by a waiter: the attempt that
    # asked died before the answer arrived.
    answer = await service.answer(second.id, option_id="reject")
    assert answer.option_id == "reject"
    assert answer.consumed is False

    await restart(one, task_id)

    assert await one.finished(run_id) == "asked"
    assert len(passes) == 2
    assert passes[0] == ["a bridge"]
    assert passes[1] == ["a bridge", "reject"]

    # Two questions, asked once each, and neither re-asked: the second
    # attempt parked on nothing, because both of its answers were already
    # there.
    rows = await one.requests_of(run_id)
    assert [row.ordinal for row in rows] == [1, 2]
    waiting = await one.events_named(run_id, EventName.task_waiting)
    assert [event.data["request_id"] for event in waiting] == [first.id, second.id]


async def test_a_replayed_form_answer_that_still_fits_is_returned_at_once(
    fleet, service: RequestService, wait_until
) -> None:
    """The other half of the gap: the answer given there still fits.

    ``form`` is the one mode whose stored value is not what the body
    asked for — an answer given while no validator was registered is
    stored raw (06 §Restart durability, D115), so the body gets an
    ``Approval`` only if ``pydantic_validator`` runs on the replay. The
    raw value here is ``{"approved": "true"}``, which is not the model and
    coerces to it: a body handed the stored dict back would fail this
    test where a body handed the validated instance passes it.

    And the question is *not* asked again. Re-asking a form answer that
    fits would cost the operator the question a second time, which is the
    whole thing D44 exists to prevent.
    """

    passes: list[list[Any]] = []

    async def body() -> str:
        got: list[Any] = []
        passes.append(got)
        got.append(await human_input("what shall I build?"))
        got.append(await human_input("sign off?", output_model=Approval))
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    first = await one.only_asked(run_id)
    await service.answer(first.id, value="a bridge")
    (_, second) = await one.asked(run_id, 2)
    await wait_until(lambda: one.parked(run_id))
    task_id = (await one.only_task(run_id)).id
    await kill(one, task_id, wait_until)

    # Stored as it arrived: `Approval` never saw it, because the waiter
    # that registered it died with its process.
    answer = await service.answer(second.id, value={"approved": "true"})
    assert answer.value == {"approved": "true"}

    await restart(one, task_id)

    assert await one.finished(run_id) == "asked"
    assert len(passes) == 2
    assert passes[0] == ["a bridge"]
    assert passes[1] == ["a bridge", Approval(approved=True, note="")]
    assert isinstance(passes[1][1], Approval)

    # No third request and no second park: the answer replayed, and the
    # re-ask path of the test below is the one that did not happen.
    rows = await one.requests_of(run_id)
    assert [row.ordinal for row in rows] == [1, 2]
    waiting = await one.events_named(run_id, EventName.task_waiting)
    assert [event.data["request_id"] for event in waiting] == [first.id, second.id]
    notes = await one.log_texts(run_id)
    assert [text for text in notes if "no longer fits" in text] == []


async def test_a_replayed_answer_that_no_longer_fits_is_asked_again(
    fleet, service: RequestService, wait_until
) -> None:
    """The gap between the crash and the re-attach (06 §Restart durability).

    No validator is registered while nothing is waiting, so the form
    answer given in that window is stored as it arrived and is only
    checked when the body comes back for it. It does not fit, so the body
    asks again — a **new** request at ordinal 4, carrying the original
    prompt and what was wrong with the last answer — and says so in the
    work log rather than silently.
    """

    got: list[Any] = []

    async def body() -> str:
        await human_input("one?")
        await human_input("two?")
        got.append(await human_input("sign off?", output_model=Approval))
        return "asked"

    one = fleet({"test": 1})
    one.register_body("asks", body)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    first = await one.only_asked(run_id)
    await service.answer(first.id, value="a bridge")
    (_, second) = await one.asked(run_id, 2)
    await service.answer(second.id, value="in stone")
    (_, _, third) = await one.asked(run_id, 3)
    await wait_until(lambda: one.parked(run_id))
    task_id = (await one.only_task(run_id)).id
    await kill(one, task_id, wait_until)

    # Answered in the gap: the request is still the operator's to answer
    # — its task is `waiting`, which is what the attempt left behind —
    # and `Approval` never sees it, because a validator belongs to a live
    # waiter and this one died with its process.
    answer = await service.answer(third.id, value={"approved": "perhaps"})
    assert answer.value == {"approved": "perhaps"}

    await restart(one, task_id)

    rows = await one.asked(run_id, 4)
    fourth: RequestRow = rows[3]
    assert fourth.ordinal == 4
    assert fourth.schema_ == Approval.model_json_schema()
    assert fourth.prompt.startswith("sign off?")
    assert "approved" in fourth.prompt
    assert "rejected" in fourth.prompt

    await service.answer(fourth.id, value={"approved": True, "note": "ship it"})
    assert await one.finished(run_id) == "asked"
    assert got == [Approval(approved=True, note="ship it")]

    # The failure was reported where an operator reads the run, not
    # swallowed into the new prompt alone.
    (note,) = [text for text in await one.log_texts(run_id) if "no longer fits" in text]
    assert f"request {third.id}" in note
    assert "Approval" in note

    # The stale answer is still on the request it was given for: history
    # keeps it, and the question that replaced it is a new row.
    stale = await service.view(third.id)
    assert stale.answer == {"approved": "perhaps"}


# --------------------------------------------------------------------------
# A retry is not a replay
# --------------------------------------------------------------------------


async def test_a_retry_starts_its_ordinals_at_one_and_asks_afresh(
    fleet, service: RequestService, wait_until
) -> None:
    """A new task row asks the question again, and gets a new answer.

    Replay is per attempt *of the same row*. Conflating it with a retry
    would answer the second attempt with the answer that helped the first
    one fail.
    """

    got: list[Any] = []

    async def body() -> str:
        answer = await human_input("what shall I build?")
        got.append(answer)
        if current_task().attempt == 1:
            raise RuntimeError("the answer was not the problem")
        return answer

    one = fleet({"test": 1})
    one.register_body("asks", body, retries=2)
    run_id = await one.submit("asks")
    await one.scheduler.start()

    first = await one.only_asked(run_id)
    await service.answer(first.id, value="a bridge")

    rows = await one.asked(run_id, 2)
    second = rows[1]
    assert second.id != first.id
    assert second.task_id != first.task_id
    assert [row.ordinal for row in rows] == [1, 1]
    assert second.prompt == "what shall I build?"

    await service.answer(second.id, value="a tunnel")
    await wait_until(lambda: one.is_completed(run_id))
    assert got == ["a bridge", "a tunnel"]
