"""Tests for :mod:`athanore.requests.service` (ports v0's ``test_requests.py``).

The v0 file drove the whole channel through an HTTP server because v0's
store *was* the service. Here the service is its own object, so the modes,
the refusals and the waiting are exercised directly and the surfaces that
sit on top of them are their own tasks' tests: ``human_input`` in T033,
the endpoints in T044a, the CLI in T054a.

Four properties carry the module, and every test below is one of them.

- **Keyed answers.** Two waiters parked on two requests each get their
  own answer and nothing of the other's, which is what makes a fan-out of
  questions safe (06 §The model).
- **One answer.** A second one is refused whether it races the first or
  merely follows it.
- **Validated where it lands.** The mode fixes the shape, a registered
  validator normalises a form, and what the validator returned is what
  the store holds.
- **No missed wake-ups.** An answer that lands between a waiter's
  decision to wait and its subscription must still wake it — the case
  that motivates subscribing before reading the store (06 §Wake-ups).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from athanore.events.bus import EventBus, Subscription
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.requests.errors import (
    AlreadyAnswered,
    InvalidAnswer,
    InvalidOption,
    RequestNotFound,
    StaleRequest,
)
from athanore.requests.service import RequestService
from athanore.requests.validators import pydantic_validator
from athanore.store.clock import now
from athanore.store.engine import make_engine
from athanore.store.rows import (
    AnswerAuthor,
    RequestKind,
    RequestMode,
    RequestRow,
    RequestSource,
    TaskStatus,
)
from athanore.store.tables import metadata
from athanore.store.uow import Reader, Store

PERMISSION_OPTIONS: list[dict[str, Any]] = [
    {"option_id": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"option_id": "reject_once", "name": "Reject", "kind": "reject_once"},
]


class Approval(BaseModel):
    approved: bool
    note: str = ""


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[Store]:
    """A store on an empty SQLite file, publishing to :func:`bus`.

    SQLite only: nothing here is a statement about a dialect, and the
    backend matrix belongs to the repository suite that owns the SQL
    (``tests/store/conftest.py``).
    """

    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    try:
        yield Store(engine, EventBus())
    finally:
        await engine.dispose()


@pytest.fixture
def bus(store: Store) -> EventBus:
    """The bus the store publishes to, which is the one the service reads."""

    assert isinstance(store.bus, EventBus)
    return store.bus


@pytest.fixture
def service(store: Store, bus: EventBus) -> RequestService:
    return RequestService(store, bus)


@pytest.fixture
async def task(store: Store) -> int:
    """One ``in_progress`` attempt of one run; its task id."""

    return await make_task(store)


async def make_task(store: Store, node: str = "ask") -> int:
    """A run with one attempt in progress, ready to be asked a question."""

    async with store.uow() as uow:
        run = await uow.runs.insert("demo", "a run")
        row = await uow.tasks.enqueue(run.id, node, None, 0, False)
        await uow.tasks.set_status(row.id, TaskStatus.in_progress.value)
        return row.id


async def run_of(store: Store, task_id: int) -> str:
    async with store.reader() as reader:
        row = await reader.tasks.get(task_id)
        assert row is not None
        return row.run_id


async def finish_task(store: Store, task_id: int) -> None:
    async with store.uow() as uow:
        await uow.tasks.finish(task_id, TaskStatus.done.value, result=None)


async def ask_text(
    service: RequestService, store: Store, task_id: int, prompt: str = "which color?"
) -> RequestRow:
    return await service.create(
        await run_of(store, task_id),
        task_id,
        prompt,
        mode=RequestMode.text,
        source=RequestSource.node,
        kind=RequestKind.question,
    )


def collect(bus: EventBus, *names: EventName) -> Subscription:
    """Subscribe to ``names`` from here on; read it with :func:`drained`."""

    return bus.subscribe([str(name) for name in names])


def drained(subscription: Subscription) -> list[Event]:
    """Everything ``subscription`` has been handed, oldest first.

    The bus fans out synchronously from the commit, so by the time the
    call that emitted an event has returned, that event is in the queue.
    """

    assert not subscription.overflowed
    events: list[Event] = []
    while not subscription.queue.empty():
        events.append(subscription.queue.get_nowait())
    return events


# --------------------------------------------------------------------------
# create
# --------------------------------------------------------------------------


async def test_create_writes_the_row_and_announces_it(
    service: RequestService, store: Store, bus: EventBus, task: int
) -> None:
    stream = collect(bus, EventName.request_opened)
    run_id = await run_of(store, task)

    request = await service.create(
        run_id,
        task,
        "Allow writing?",
        mode=RequestMode.options,
        source=RequestSource.agent,
        kind=RequestKind.permission,
        options=PERMISSION_OPTIONS,
        tool_call={"toolCallId": "call_1"},
        ordinal=None,
    )

    assert (request.run_id, request.task_id) == (run_id, task)
    assert request.mode is RequestMode.options
    assert request.source is RequestSource.agent
    assert request.kind is RequestKind.permission
    events = drained(stream)
    assert [event.name for event in events] == [EventName.request_opened]
    assert events[0].data == {
        "request_id": request.id,
        "mode": "options",
        "kind": "permission",
        "source": "agent",
        "node": "ask",
    }
    assert (events[0].run_id, events[0].task_id) == (run_id, task)
    assert events[0].id is not None, "the event is stored, not only published"


async def test_create_carries_the_ordinal_of_a_node_request(
    service: RequestService, store: Store, bus: EventBus, task: int
) -> None:
    stream = collect(bus, EventName.request_opened)

    request = await service.create(
        await run_of(store, task),
        task,
        "again?",
        mode=RequestMode.text,
        source=RequestSource.node,
        kind=RequestKind.question,
        ordinal=2,
    )

    assert request.ordinal == 2
    assert drained(stream)[0].data["ordinal"] == 2


async def test_options_request_needs_options(
    service: RequestService, store: Store, task: int
) -> None:
    """An `options` request with nothing to choose from is unanswerable."""

    with pytest.raises(ValueError, match="needs the options"):
        await service.create(
            await run_of(store, task),
            task,
            "ship it?",
            mode=RequestMode.options,
            source=RequestSource.node,
            kind=RequestKind.question,
        )

    assert await service.inbox() == []


async def test_reopen_finds_the_request_this_task_asked_at_that_ordinal(
    service: RequestService, store: Store, task: int
) -> None:
    assert await service.reopen(task, 1) is None

    request = await service.create(
        await run_of(store, task),
        task,
        "what is the answer?",
        mode=RequestMode.text,
        source=RequestSource.node,
        kind=RequestKind.question,
        ordinal=1,
    )

    reopened = await service.reopen(task, 1)
    assert reopened is not None and reopened.id == request.id
    await service.answer(request.id, value="42")
    still = await service.reopen(task, 1)
    assert still is not None and still.id == request.id, (
        "an answered request is reopened too: the answer replays"
    )
    assert await service.reopen(task, 2) is None


# --------------------------------------------------------------------------
# answer: the modes
# --------------------------------------------------------------------------


async def test_text_answer_round_trip(
    service: RequestService, store: Store, bus: EventBus, task: int
) -> None:
    request = await ask_text(service, store, task)
    assert [view.id for view in await service.inbox()] == [request.id]
    stream = collect(bus, EventName.request_answered)

    with pytest.raises(InvalidAnswer):
        await service.answer(request.id, value="")
    with pytest.raises(InvalidAnswer):
        await service.answer(request.id, value="   ")
    with pytest.raises(InvalidAnswer):
        await service.answer(request.id, value={"not": "text"})
    with pytest.raises(InvalidAnswer):
        await service.answer(request.id, option_id="blue")
    assert [view.id for view in await service.inbox()] == [request.id], (
        "a refused answer leaves the request open"
    )

    answer = await service.answer(request.id, value="blue")
    assert (answer.request_id, answer.value) == (request.id, "blue")
    assert answer.option_id is None and answer.consumed is False
    assert answer.author is AnswerAuthor.user
    assert await service.inbox() == []
    assert [event.data for event in drained(stream)] == [
        {"request_id": request.id, "author": "user"}
    ]


async def test_options_answer_takes_an_offered_id(
    service: RequestService, store: Store, bus: EventBus, task: int
) -> None:
    request = await service.create(
        await run_of(store, task),
        task,
        "Allow writing?",
        mode=RequestMode.options,
        source=RequestSource.agent,
        kind=RequestKind.permission,
        options=PERMISSION_OPTIONS,
    )
    stream = collect(bus, EventName.request_answered)

    with pytest.raises(InvalidOption):
        await service.answer(request.id, option_id="maybe")
    with pytest.raises(InvalidOption):
        await service.answer(request.id, value="allow_once")

    answer = await service.answer(request.id, option_id="allow_once")
    assert (answer.option_id, answer.value) == ("allow_once", None)
    assert drained(stream)[0].data["option_id"] == "allow_once"


async def test_an_engine_answer_is_recorded_as_the_engine(
    service: RequestService, store: Store, bus: EventBus, task: int
) -> None:
    """The headless fallbacks of 06 §Timeouts author their own answer."""

    request = await service.create(
        await run_of(store, task),
        task,
        "Allow writing?",
        mode=RequestMode.options,
        source=RequestSource.agent,
        kind=RequestKind.permission,
        options=PERMISSION_OPTIONS,
    )
    stream = collect(bus, EventName.request_answered)

    answer = await service.answer(
        request.id, option_id="reject_once", author=AnswerAuthor.engine
    )

    assert answer.author is AnswerAuthor.engine
    assert drained(stream)[0].data["author"] == "engine"
    view = await service.view(request.id)
    assert view.answered_by is AnswerAuthor.engine and view.answer == "reject_once"


async def test_form_answer_must_be_an_object(
    service: RequestService, store: Store, task: int
) -> None:
    request = await service.create(
        await run_of(store, task),
        task,
        "sign off",
        mode=RequestMode.form,
        source=RequestSource.node,
        kind=RequestKind.question,
        schema=Approval.model_json_schema(),
    )

    with pytest.raises(InvalidAnswer):
        await service.answer(request.id, value="not an object")

    # With no validator registered, the object shape is the whole contract.
    answer = await service.answer(request.id, value={"anything": 1})
    assert answer.value == {"anything": 1}


async def test_form_answer_stores_what_the_validator_returned(
    service: RequestService, store: Store, task: int
) -> None:
    """Normalisation happens once, at the door, and is what is stored."""

    request = await service.create(
        await run_of(store, task),
        task,
        "sign off",
        mode=RequestMode.form,
        source=RequestSource.node,
        kind=RequestKind.question,
        schema=Approval.model_json_schema(),
    )
    service.register_validator(request.id, pydantic_validator(Approval))

    with pytest.raises(InvalidAnswer) as refused:
        await service.answer(request.id, value={"note": "x"})
    assert [error["loc"] for error in refused.value.errors] == [("approved",)]
    assert [view.id for view in await service.inbox()] == [request.id]

    answer = await service.answer(request.id, value={"approved": 1})

    assert answer.value == {"approved": True, "note": ""}
    view = await service.view(request.id)
    assert view.answer == {"approved": True, "note": ""}


async def test_unregister_validator_leaves_only_the_object_shape(
    service: RequestService, store: Store, task: int
) -> None:
    request = await service.create(
        await run_of(store, task),
        task,
        "sign off",
        mode=RequestMode.form,
        source=RequestSource.node,
        kind=RequestKind.question,
        schema=Approval.model_json_schema(),
    )
    service.register_validator(request.id, pydantic_validator(Approval))
    service.unregister_validator(request.id)
    service.unregister_validator(request.id)  # idempotent

    answer = await service.answer(request.id, value={"note": "x"})

    assert answer.value == {"note": "x"}


# --------------------------------------------------------------------------
# answer: the refusals
# --------------------------------------------------------------------------


async def test_answering_an_unknown_request_is_a_404(
    service: RequestService,
) -> None:
    with pytest.raises(RequestNotFound):
        await service.answer(42, value="x")
    with pytest.raises(RequestNotFound):
        await service.view(42)


async def test_waiting_on_an_unknown_request_is_a_404(
    service: RequestService,
) -> None:
    """Nothing will ever answer it, so the wait says so instead of expiring."""

    with pytest.raises(RequestNotFound):
        await asyncio.wait_for(service.wait(42, timeout=5), 5)
    with pytest.raises(RequestNotFound):
        await asyncio.wait_for(service.poll(42, 5), 5)


async def test_a_second_answer_is_refused(
    service: RequestService, store: Store, task: int
) -> None:
    request = await ask_text(service, store, task)
    await service.answer(request.id, value="blue")

    with pytest.raises(AlreadyAnswered):
        await service.answer(request.id, value="red")

    view = await service.view(request.id)
    assert view.answer == "blue", "the first answer stands"


async def test_a_second_answer_that_races_the_first_is_refused(
    service: RequestService, store: Store, task: int
) -> None:
    """The unique constraint is the guard; the pre-check is the message.

    Both answers pass the read — there is no answer yet when either of
    them looks — so the refusal can only come from the insert.
    """

    request = await ask_text(service, store, task)

    outcomes = await asyncio.gather(
        service.answer(request.id, value="blue"),
        service.answer(request.id, value="red"),
        return_exceptions=True,
    )

    refused = [out for out in outcomes if isinstance(out, BaseException)]
    assert len(refused) == 1 and isinstance(refused[0], AlreadyAnswered)
    kept = [out for out in outcomes if not isinstance(out, BaseException)]
    view = await service.view(request.id)
    assert view.answer == kept[0].value


async def test_a_request_goes_stale_when_its_task_finishes(
    service: RequestService, store: Store, task: int
) -> None:
    request = await ask_text(service, store, task)
    assert [view.id for view in await service.inbox()] == [request.id]

    await finish_task(store, task)

    with pytest.raises(StaleRequest):
        await service.answer(request.id, value="blue")
    assert await service.inbox() == [], "a stale request leaves the inbox"
    history = await service.list_for_run(await run_of(store, task))
    assert [(view.id, view.pending, view.stale) for view in history] == [
        (request.id, False, True)
    ], "and stays in the run's history"


async def test_a_stale_request_that_was_answered_reports_already_answered(
    service: RequestService, store: Store, task: int
) -> None:
    """Answered outranks stale: the answer is the fact worth reporting."""

    request = await ask_text(service, store, task)
    await service.answer(request.id, value="blue")
    await finish_task(store, task)

    with pytest.raises(AlreadyAnswered):
        await service.answer(request.id, value="red")


# --------------------------------------------------------------------------
# wait and poll
# --------------------------------------------------------------------------


async def test_wait_returns_the_answer_and_claims_it(
    service: RequestService, store: Store, task: int
) -> None:
    request = await ask_text(service, store, task)
    waiter = asyncio.create_task(service.wait(request.id))
    await asyncio.sleep(0)

    await service.answer(request.id, value="blue")

    answer = await asyncio.wait_for(waiter, 5)
    assert answer.value == "blue"
    assert answer.consumed is True


async def test_wait_sees_an_answer_that_landed_before_it_subscribed(
    service: RequestService, store: Store, task: int
) -> None:
    """The missed wake-up: the answer is already there when the wait starts.

    The store commits and then publishes, so the ``request.answered`` for
    this answer was fanned out before :meth:`RequestService.wait` was
    called at all. Nothing will ever wake this waiter; only the re-read
    of the store can end it.
    """

    request = await ask_text(service, store, task)
    await service.answer(request.id, value="blue")

    answer = await asyncio.wait_for(service.wait(request.id, timeout=5), 5)

    assert answer.value == "blue" and answer.consumed is True


async def test_wait_subscribes_before_it_reads_the_store(
    service: RequestService, store: Store, bus: EventBus, task: int
) -> None:
    """The ordering the guard *is*, asserted rather than inferred.

    The test above shows the store re-read happening; this one shows it
    happening second. Reversed, the two lines leave a window — the answer
    that lands after the read and before the subscription is published to
    a subscription that does not exist yet, and the waiter parks on a
    question that has already been answered.
    """

    request = await ask_text(service, store, task)
    subscribed: list[int] = []
    original = store.reader

    @asynccontextmanager
    async def watched() -> AsyncIterator[Reader]:
        subscribed.append(len(bus.subscriptions))
        async with original() as reader:
            yield reader

    store.reader = watched  # type: ignore[method-assign]
    try:
        waiter = asyncio.create_task(service.wait(request.id, timeout=5))
        await asyncio.sleep(0.05)
        assert subscribed[:1] == [1], (
            "the first read of the store happened with the subscription "
            "already in place"
        )
    finally:
        del store.reader  # type: ignore[misc]

    await service.answer(request.id, value="blue")
    assert (await asyncio.wait_for(waiter, 5)).value == "blue"


async def test_two_waiters_get_their_own_answers(
    service: RequestService, store: Store
) -> None:
    """Keyed, not broadcast: one answer wakes one waiter (06 §The model)."""

    task_a = await make_task(store, "a")
    task_b = await make_task(store, "b")
    request_a = await ask_text(service, store, task_a, "a?")
    request_b = await ask_text(service, store, task_b, "b?")

    waiter_a = asyncio.create_task(service.wait(request_a.id))
    waiter_b = asyncio.create_task(service.wait(request_b.id))
    await asyncio.sleep(0.05)

    await service.answer(request_b.id, value="for b")
    assert (await asyncio.wait_for(waiter_b, 5)).value == "for b"
    await asyncio.sleep(0.05)
    assert not waiter_a.done(), "b's answer is not a's"

    await service.answer(request_a.id, value="for a")
    assert (await asyncio.wait_for(waiter_a, 5)).value == "for a"


async def test_wait_times_out_and_leaves_the_request_answerable(
    service: RequestService, store: Store, task: int
) -> None:
    request = await ask_text(service, store, task)

    with pytest.raises(TimeoutError):
        await service.wait(request.id, timeout=0.05)

    assert [view.id for view in await service.inbox()] == [request.id]
    assert (await service.answer(request.id, value="late")).value == "late"


async def test_poll_returns_the_answer_without_claiming_it(
    service: RequestService, store: Store, task: int
) -> None:
    """The agent long-poll re-delivers: asking twice is asking once, twice."""

    request = await ask_text(service, store, task)
    poller = asyncio.create_task(service.poll(request.id, 5))
    await asyncio.sleep(0)
    await service.answer(request.id, value="blue")

    first = await asyncio.wait_for(poller, 5)
    assert first is not None and first.value == "blue"
    assert first.consumed is False

    second = await service.poll(request.id, 5)
    assert second is not None and second.value == "blue"
    assert second.consumed is False


async def test_poll_returns_none_when_the_wait_expires(
    service: RequestService, store: Store, task: int
) -> None:
    request = await ask_text(service, store, task)

    assert await service.poll(request.id, 0.05) is None


async def test_a_waiter_is_not_woken_by_an_unrelated_event(
    service: RequestService, store: Store, bus: EventBus, task: int
) -> None:
    """Only ``request.answered`` for *this* id ends the wait."""

    request = await ask_text(service, store, task)
    waiter = asyncio.create_task(service.wait(request.id, timeout=5))
    await asyncio.sleep(0.05)

    bus.publish(
        Event(
            run_id=await run_of(store, task),
            task_id=task,
            name=EventName.request_answered,
            data={"request_id": request.id + 1000, "author": "user"},
            created=now(),
        )
    )
    await asyncio.sleep(0.05)
    assert not waiter.done()

    await service.answer(request.id, value="blue")
    assert (await asyncio.wait_for(waiter, 5)).value == "blue"


# --------------------------------------------------------------------------
# reading
# --------------------------------------------------------------------------


async def test_the_inbox_spans_runs_and_holds_only_the_pending(
    service: RequestService, store: Store
) -> None:
    task_a = await make_task(store, "a")
    task_b = await make_task(store, "b")
    request_a = await ask_text(service, store, task_a, "a?")
    request_b = await ask_text(service, store, task_b, "b?")
    await service.answer(request_b.id, value="done")
    open_b = await ask_text(service, store, task_b, "b again?")

    assert [view.id for view in await service.inbox()] == [
        request_a.id,
        open_b.id,
    ]
    run_b = await run_of(store, task_b)
    assert [view.id for view in await service.list_for_run(run_b)] == [
        request_b.id,
        open_b.id,
    ], "a run's list keeps the answered ones"
