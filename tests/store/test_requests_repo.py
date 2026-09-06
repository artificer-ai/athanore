"""Tests for :mod:`athanore.store.repos.requests`.

Two properties carry the module. **One answer per request**: the primary
key on ``answers.request_id`` is the mechanism, and the repository lets
its :exc:`~sqlalchemy.exc.IntegrityError` out rather than absorbing the
race the constraint exists to detect (06 §The model). **Pending is not
"unanswered"**: a request whose task has ended is stale — nobody will
consume an answer to it — and it must leave the operator's inbox while
staying in the run's history (06 §Restart durability). Every pending/stale
assertion here is made by moving the *task's* status and nothing else,
because that is the only thing the distinction is allowed to depend on.

Every test runs on both backends; see ``tests/store/conftest.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from freezegun import freeze_time
from sqlalchemy.exc import IntegrityError

from athanore.store.rows import (
    AnswerAuthor,
    RequestKind,
    RequestMode,
    RequestSource,
    TaskStatus,
)
from athanore.store.tables import tasks
from athanore.store.uow import Store, now

PERMISSION_OPTIONS: list[dict[str, Any]] = [
    {"option_id": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"option_id": "reject_once", "name": "Reject", "kind": "reject_once"},
]


async def make_run(store: Store, title: str = "a run") -> str:
    async with store.uow() as uow:
        run = await uow.runs.insert("demo", title)
        return run.id


async def make_task(
    store: Store,
    run_id: str,
    node: str = "build",
    status: TaskStatus = TaskStatus.in_progress,
) -> int:
    """One task attempt of ``run_id``, in ``status``."""

    async with store.uow() as uow:
        result = await uow.conn.execute(
            tasks.insert()
            .values(
                run_id=run_id,
                node=node,
                attempt=1,
                status=status.value,
                priority=0,
                created=now(),
                terminal=False,
                branch=[],
            )
            .returning(tasks.c.id)
        )
        return int(result.scalar_one())


async def set_status(store: Store, task_id: int, status: TaskStatus) -> None:
    async with store.uow() as uow:
        await uow.tasks.set_status(task_id, status.value)


async def ask_permission(
    store: Store, run_id: str, task_id: int, prompt: str = "Allow writing?"
) -> int:
    """One agent-raised permission request; its id."""

    async with store.uow() as uow:
        request = await uow.requests.create(
            run_id,
            task_id,
            prompt,
            mode=RequestMode.options,
            source=RequestSource.agent,
            kind=RequestKind.permission,
            options=PERMISSION_OPTIONS,
            tool_call={"toolCallId": "call_1"},
        )
        return request.id


# --------------------------------------------------------------------------
# create / get / by_ordinal
# --------------------------------------------------------------------------


async def test_create_returns_the_row_it_wrote(store: Store) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)

    async with store.uow() as uow:
        request = await uow.requests.create(
            run_id,
            task_id,
            "Allow writing to the repository?",
            mode=RequestMode.options,
            source=RequestSource.agent,
            kind=RequestKind.permission,
            options=PERMISSION_OPTIONS,
            tool_call={"toolCallId": "call_1"},
        )

    assert (request.run_id, request.task_id) == (run_id, task_id)
    assert request.prompt == "Allow writing to the repository?"
    assert (request.mode, request.source, request.kind) == (
        RequestMode.options,
        RequestSource.agent,
        RequestKind.permission,
    )
    assert request.options == PERMISSION_OPTIONS
    assert request.tool_call == {"toolCallId": "call_1"}
    assert (request.ordinal, request.schema_) == (None, None)
    assert request.created.tzinfo is not None

    async with store.reader() as reader:
        assert await reader.requests.get(request.id) == request


async def test_a_form_request_round_trips_its_schema(store: Store) -> None:
    """The column 08 spells ``schema`` reaches the read model's ``schema_``."""

    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    schema = {"type": "object", "properties": {"branch": {"type": "string"}}}

    async with store.uow() as uow:
        request = await uow.requests.create(
            run_id,
            task_id,
            "Which branch?",
            mode=RequestMode.form,
            source=RequestSource.node,
            kind=RequestKind.elicitation,
            schema=schema,
            ordinal=1,
        )

    assert request.schema_ == schema
    assert request.model_dump(by_alias=True)["schema"] == schema


async def test_get_and_view_answer_none_for_an_unknown_id(store: Store) -> None:
    async with store.reader() as reader:
        assert await reader.requests.get(404) is None
        assert await reader.requests.view(404) is None


async def test_by_ordinal_finds_the_request_and_a_gap_is_none(store: Store) -> None:
    """What a recovered body reads: the ordinal it is about to ask at."""

    run_id = await make_run(store)
    task_id = await make_task(store, run_id)

    async with store.uow() as uow:
        first = await uow.requests.create(
            run_id,
            task_id,
            "Which deliverable?",
            mode=RequestMode.text,
            source=RequestSource.node,
            kind=RequestKind.question,
            ordinal=1,
        )
        third = await uow.requests.create(
            run_id,
            task_id,
            "Ship it?",
            mode=RequestMode.text,
            source=RequestSource.node,
            kind=RequestKind.question,
            ordinal=3,
        )

    async with store.reader() as reader:
        assert await reader.requests.by_ordinal(task_id, 1) == first
        assert await reader.requests.by_ordinal(task_id, 2) is None
        assert await reader.requests.by_ordinal(task_id, 3) == third


async def test_an_ordinal_is_per_task_row(store: Store) -> None:
    """A retry is a new task row, so its ordinals start at 1 again (06)."""

    run_id = await make_run(store)
    first_attempt = await make_task(store, run_id)
    second_attempt = await make_task(store, run_id)

    async with store.uow() as uow:
        for task_id in (first_attempt, second_attempt):
            await uow.requests.create(
                run_id,
                task_id,
                "Which deliverable?",
                mode=RequestMode.text,
                source=RequestSource.node,
                kind=RequestKind.question,
                ordinal=1,
            )

    async with store.reader() as reader:
        one = await reader.requests.by_ordinal(first_attempt, 1)
        two = await reader.requests.by_ordinal(second_attempt, 1)

    assert one is not None and two is not None
    assert one.id != two.id


async def test_a_second_request_at_the_same_ordinal_raises(store: Store) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)

    async with store.uow() as uow:
        await uow.requests.create(
            run_id,
            task_id,
            "Which deliverable?",
            mode=RequestMode.text,
            source=RequestSource.node,
            kind=RequestKind.question,
            ordinal=1,
        )

    with pytest.raises(IntegrityError):
        async with store.uow() as uow:
            await uow.requests.create(
                run_id,
                task_id,
                "Which deliverable, again?",
                mode=RequestMode.text,
                source=RequestSource.node,
                kind=RequestKind.question,
                ordinal=1,
            )


async def test_a_task_may_raise_many_requests_without_an_ordinal(store: Store) -> None:
    """The unique index is partial: agent-raised requests carry no ordinal."""

    run_id = await make_run(store)
    task_id = await make_task(store, run_id)

    first = await ask_permission(store, run_id, task_id, "Allow writing?")
    second = await ask_permission(store, run_id, task_id, "Allow the network?")

    async with store.reader() as reader:
        views = await reader.requests.list_views(run_id)

    assert [view.id for view in views] == [first, second]


# --------------------------------------------------------------------------
# answer / mark_consumed
# --------------------------------------------------------------------------


async def test_answer_records_the_one_answer(store: Store) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    request_id = await ask_permission(store, run_id, task_id)

    async with store.uow() as uow:
        answer = await uow.requests.answer(
            request_id, AnswerAuthor.user, option_id="allow_once"
        )

    assert answer.request_id == request_id
    assert (answer.author, answer.option_id) == (AnswerAuthor.user, "allow_once")
    assert (answer.value, answer.consumed) == (None, False)
    assert answer.created.tzinfo is not None


async def test_a_second_answer_raises(store: Store) -> None:
    """One answer per request, claimed exactly once (06 §The model)."""

    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    request_id = await ask_permission(store, run_id, task_id)

    async with store.uow() as uow:
        await uow.requests.answer(request_id, AnswerAuthor.user, option_id="allow_once")

    with pytest.raises(IntegrityError):
        async with store.uow() as uow:
            await uow.requests.answer(
                request_id, AnswerAuthor.engine, option_id="reject_once"
            )

    async with store.reader() as reader:
        view = await reader.requests.view(request_id)

    assert view is not None
    assert (view.answer, view.answered_by) == ("allow_once", AnswerAuthor.user)


async def test_an_answer_to_no_request_raises(store: Store) -> None:
    with pytest.raises(IntegrityError):
        async with store.uow() as uow:
            await uow.requests.answer(404, AnswerAuthor.user, value="hello")


async def test_mark_consumed_claims_the_answer(store: Store) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    request_id = await ask_permission(store, run_id, task_id)

    async with store.uow() as uow:
        await uow.requests.answer(request_id, AnswerAuthor.user, option_id="allow_once")

    async with store.uow() as uow:
        claimed = await uow.requests.mark_consumed(request_id)
        # A replay on the same task row is not a second waiter, so
        # claiming again is not an error.
        again = await uow.requests.mark_consumed(request_id)

    assert claimed is not None and claimed.consumed is True
    assert again is not None and again.consumed is True


async def test_mark_consumed_is_none_when_there_is_no_answer(store: Store) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    request_id = await ask_permission(store, run_id, task_id)

    async with store.uow() as uow:
        assert await uow.requests.mark_consumed(request_id) is None


# --------------------------------------------------------------------------
# view: pending, stale, answered
# --------------------------------------------------------------------------


@pytest.mark.parametrize("status", [TaskStatus.in_progress, TaskStatus.waiting])
async def test_an_unanswered_request_is_pending_while_its_task_lives(
    store: Store, status: TaskStatus
) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id, node="implement", status=status)
    request_id = await ask_permission(store, run_id, task_id)

    async with store.reader() as reader:
        view = await reader.requests.view(request_id)

    assert view is not None
    assert (view.pending, view.stale) == (True, False)
    assert (view.answer, view.answered_by) == (None, None)
    assert view.node == "implement"
    assert (view.run_id, view.task_id) == (run_id, task_id)
    assert view.options == PERMISSION_OPTIONS
    assert view.tool_call == {"toolCallId": "call_1"}


@pytest.mark.parametrize(
    "status",
    [
        TaskStatus.ready,
        TaskStatus.done,
        TaskStatus.failed,
        TaskStatus.dead_letter,
        TaskStatus.cancelled,
    ],
)
async def test_an_unanswered_request_is_stale_once_its_task_is_not_live(
    store: Store, status: TaskStatus
) -> None:
    """The attempt that asked is gone, so nobody will consume an answer."""

    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    request_id = await ask_permission(store, run_id, task_id)
    await set_status(store, task_id, status)

    async with store.reader() as reader:
        view = await reader.requests.view(request_id)

    assert view is not None
    assert (view.pending, view.stale) == (False, True)


async def test_the_same_request_goes_pending_to_stale_on_its_task_alone(
    store: Store,
) -> None:
    """One request, one changed task status, both flags flipped."""

    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    request_id = await ask_permission(store, run_id, task_id)

    async with store.reader() as reader:
        live = await reader.requests.view(request_id)
    await set_status(store, task_id, TaskStatus.failed)
    async with store.reader() as reader:
        dead = await reader.requests.view(request_id)

    assert live is not None and dead is not None
    assert (live.pending, live.stale) == (True, False)
    assert (dead.pending, dead.stale) == (False, True)
    assert live.prompt == dead.prompt


async def test_an_answered_request_is_neither_pending_nor_stale(store: Store) -> None:
    run_id = await make_run(store)
    task_id = await make_task(store, run_id)
    request_id = await ask_permission(store, run_id, task_id)

    async with store.uow() as uow:
        await uow.requests.answer(request_id, AnswerAuthor.user, option_id="allow_once")

    async with store.reader() as reader:
        live = await reader.requests.view(request_id)
    await set_status(store, task_id, TaskStatus.done)
    async with store.reader() as reader:
        finished = await reader.requests.view(request_id)

    for view in (live, finished):
        assert view is not None
        assert (view.pending, view.stale) == (False, False)
        assert (view.answer, view.answered_by) == ("allow_once", AnswerAuthor.user)


async def test_the_view_folds_option_id_and_value_into_one_answer(
    store: Store,
) -> None:
    """``options`` is answered by id, ``text`` and ``form`` by value (08)."""

    run_id = await make_run(store)
    task_id = await make_task(store, run_id)

    async with store.uow() as uow:
        text = await uow.requests.create(
            run_id,
            task_id,
            "Which deliverable?",
            mode=RequestMode.text,
            source=RequestSource.node,
            kind=RequestKind.question,
            ordinal=1,
        )
        form = await uow.requests.create(
            run_id,
            task_id,
            "Describe the branch",
            mode=RequestMode.form,
            source=RequestSource.node,
            kind=RequestKind.question,
            schema={"type": "object"},
            ordinal=2,
        )
        await uow.requests.answer(text.id, AnswerAuthor.user, value="the parser")
        await uow.requests.answer(
            form.id, AnswerAuthor.engine, value={"branch": "feat/T016"}
        )

    async with store.reader() as reader:
        answered = {view.id: view for view in await reader.requests.list_views(run_id)}

    assert answered[text.id].answer == "the parser"
    assert answered[text.id].answered_by == AnswerAuthor.user
    assert answered[form.id].answer == {"branch": "feat/T016"}
    assert answered[form.id].answered_by == AnswerAuthor.engine


async def test_the_view_measures_age_from_created(store: Store) -> None:
    with freeze_time("2026-09-06 12:00:00") as clock:
        run_id = await make_run(store)
        task_id = await make_task(store, run_id)
        request_id = await ask_permission(store, run_id, task_id)

        async with store.reader() as reader:
            fresh = await reader.requests.view(request_id)
        clock.tick(90.0)
        async with store.reader() as reader:
            older = await reader.requests.view(request_id)

    assert fresh is not None and older is not None
    assert fresh.age == 0.0
    assert older.age == 90.0
    assert older.created == fresh.created


# --------------------------------------------------------------------------
# list_views
# --------------------------------------------------------------------------


async def test_the_inbox_excludes_the_answered_and_the_stale(store: Store) -> None:
    """``pending_only`` is ``GET /api/requests?pending=true`` (08)."""

    run_id = await make_run(store)
    live_task = await make_task(store, run_id, node="implement")
    dead_task = await make_task(store, run_id, node="review")

    open_request = await ask_permission(store, run_id, live_task, "Allow writing?")
    answered = await ask_permission(store, run_id, live_task, "Allow the network?")
    stale = await ask_permission(store, run_id, dead_task, "Allow the shell?")

    async with store.uow() as uow:
        await uow.requests.answer(answered, AnswerAuthor.user, option_id="allow_once")
    await set_status(store, dead_task, TaskStatus.failed)

    async with store.reader() as reader:
        every = await reader.requests.list_views(run_id)
        inbox = await reader.requests.list_views(run_id, pending_only=True)

    assert [view.id for view in every] == [open_request, answered, stale]
    assert [view.id for view in inbox] == [open_request]


async def test_the_inbox_spans_runs_and_a_run_filter_narrows_it(store: Store) -> None:
    first_run = await make_run(store, "first")
    second_run = await make_run(store, "second")
    first_task = await make_task(store, first_run)
    second_task = await make_task(store, second_run)

    first_request = await ask_permission(store, first_run, first_task)
    second_request = await ask_permission(store, second_run, second_task)

    async with store.reader() as reader:
        everywhere = await reader.requests.list_views(pending_only=True)
        just_first = await reader.requests.list_views(first_run, pending_only=True)

    assert [view.id for view in everywhere] == [first_request, second_request]
    assert [view.run_id for view in everywhere] == [first_run, second_run]
    assert [view.id for view in just_first] == [first_request]


async def test_list_views_is_empty_for_a_run_with_no_requests(store: Store) -> None:
    run_id = await make_run(store)

    async with store.reader() as reader:
        assert await reader.requests.list_views(run_id) == []


async def test_the_inbox_agrees_with_the_run_list_count(store: Store) -> None:
    """``RunSummary.pending_requests`` and ``pending`` are one rule (07)."""

    run_id = await make_run(store)
    live_task = await make_task(store, run_id)
    dead_task = await make_task(store, run_id, node="review")
    await ask_permission(store, run_id, live_task, "Allow writing?")
    answered = await ask_permission(store, run_id, live_task, "Allow the network?")
    await ask_permission(store, run_id, dead_task, "Allow the shell?")

    async with store.uow() as uow:
        await uow.requests.answer(answered, AnswerAuthor.user, option_id="allow_once")
    await set_status(store, dead_task, TaskStatus.dead_letter)

    async with store.reader() as reader:
        summaries = await reader.runs.list()
        inbox = await reader.requests.list_views(run_id, pending_only=True)

    assert len(summaries) == 1
    assert summaries[0].pending_requests == len(inbox) == 1
