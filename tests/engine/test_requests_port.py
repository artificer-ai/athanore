"""The request port a node body is handed, and the ordinal behind it (T032).

``ctx.services.requests`` is the whole of what a body can do to the
request channel, and the whole of what this file is about. The service
under it is ``tests/requests/test_service.py``'s subject; what is asserted
here is the layer that decides *which* request a call means:

- **A node's questions are numbered.** The first ``reopen_or_create`` of
  an attempt is ordinal 1, the second is 2, and the counter lives on the
  :class:`~athanore.engine.context.TaskContext` — which is to say on the
  attempt, not on the process.
- **So a re-executed body re-attaches instead of re-asking.** This is the
  test the ordinal exists for (06 §Restart durability): a body that opened
  two requests and died opens *none* on the way back, and the answer given
  while nothing was waiting is still on the request it was given for.
  Without it, a crash costs the operator every question again.
- **A retry asks afresh.** A new task row starts at ordinal 1, because the
  answers of a failed attempt may have been the reason it failed.
- **An agent's requests are not numbered.** They come from inside a turn
  that a re-execution does not reproduce statement for statement, so
  numbering them by position would replay one answer onto a different
  question.
- **The engine can answer.** ``answer_as_engine`` is the headless
  fallback of 06 §Timeouts, and it says ``engine`` in the row.

The port is exercised through :func:`~athanore.engine.runner.run_attempt`
rather than in isolation, because "the runner wires this" is half of what
T032 is: either a body reaches the real channel, or nobody is ever asked
anything.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from athanore.engine.context import current_task
from athanore.engine.services import TaskRequests
from athanore.requests.service import RequestService
from athanore.store.rows import (
    AnswerAuthor,
    RequestKind,
    RequestMode,
    RequestRow,
    RequestSource,
    TaskStatus,
)
from athanore.store.uow import Store
from athanore.workflow import Workflow

WORKFLOW = "asking"

#: The fuse on the one test that parks a body on an answer. Reached only
#: when the wake-up is broken, so it is generous.
DEADLINE = 5.0

OPTIONS: list[dict[str, Any]] = [
    {"option_id": "yes", "name": "Yes", "kind": "allow_once"},
    {"option_id": "no", "name": "No", "kind": "reject_once"},
]


# --------------------------------------------------------------------------
# Reading the store back
# --------------------------------------------------------------------------


async def requests_of(store: Store, run_id: str) -> list[RequestRow]:
    """Every request of ``run_id``, oldest first, as rows.

    Rows rather than views: ``ordinal`` is the column this file is about
    and a :class:`~athanore.store.rows.RequestView` does not carry it —
    it is the engine's bookkeeping, not something the wire shows.
    """

    async with store.reader() as reader:
        views = await reader.requests.list_views(run_id)
        rows = [await reader.requests.get(view.id) for view in views]
    return [row for row in rows if row is not None]


async def recover_the_row(store: Store) -> list[int]:
    """What ``recover()`` does to the attempt a crash left behind."""

    async with store.uow() as uow:
        return await uow.tasks.reset_for_recovery()


# --------------------------------------------------------------------------
# Numbering
# --------------------------------------------------------------------------


async def test_each_question_of_an_attempt_takes_the_next_ordinal(
    harness, store: Store
) -> None:
    """Two questions, two requests, ordinals 1 and 2 on this task row."""

    opened: list[RequestRow] = []
    wf = Workflow(WORKFLOW)

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        for prompt in ("first?", "second?"):
            opened.append(
                await ctx.services.requests.reopen_or_create(
                    prompt, mode=RequestMode.text, kind=RequestKind.question
                )
            )

    harness.register(wf)
    run_id = await harness.submit(WORKFLOW)
    claimed = await harness.attempt()

    rows = await requests_of(store, run_id)
    assert [row.prompt for row in rows] == ["first?", "second?"]
    assert [row.ordinal for row in rows] == [1, 2]
    assert {row.source for row in rows} == {RequestSource.node}
    assert {row.kind for row in rows} == {RequestKind.question}
    assert {row.task_id for row in rows} == {claimed.task.id}
    assert {row.run_id for row in rows} == {run_id}
    # The body was handed exactly the rows the store holds.
    assert [row.id for row in opened] == [row.id for row in rows]


async def test_a_re_executed_body_re_attaches_to_the_requests_it_opened(
    harness, store: Store, requests_service: RequestService
) -> None:
    """The point of the ordinal (06 §Restart durability).

    A body opens two questions and the process dies on the second. The row
    goes back to ``ready`` with recovery, the body runs again from the top
    — and asks nothing: both calls land on the requests that are already
    there, so the operator is not asked four questions for two.

    The answer that arrived while nothing was waiting is still attached to
    the request it answered, which is what makes T033a's replay possible at
    all: re-asking would have orphaned it.
    """

    passes: list[list[RequestRow]] = []
    wf = Workflow(WORKFLOW)

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        opened: list[RequestRow] = []
        passes.append(opened)
        for prompt in ("first?", "second?"):
            opened.append(
                await ctx.services.requests.reopen_or_create(
                    prompt, mode=RequestMode.text, kind=RequestKind.question
                )
            )
        if len(passes) == 1:
            # The process dies: no status written, the row left
            # `in_progress` for recovery (04 §Shutdown).
            raise asyncio.CancelledError

    harness.register(wf)
    run_id = await harness.submit(WORKFLOW)

    claimed = await harness.claim()
    with pytest.raises(asyncio.CancelledError):
        await harness.spawn(claimed[0])
    first_pass = passes[0]
    assert [row.ordinal for row in first_pass] == [1, 2]

    # Somebody answers question one in the gap, while no waiter exists.
    task_id = claimed[0].task.id
    assert (await harness.task(task_id)).status is TaskStatus.in_progress
    await requests_service.answer(first_pass[0].id, value="the answer")

    assert await recover_the_row(store) == [task_id]
    second = await harness.claim()
    assert second[0].task.id == task_id
    await harness.spawn(second[0])

    # Two requests exist, not four, and they are the same two.
    rows = await requests_of(store, run_id)
    assert [row.id for row in rows] == [row.id for row in first_pass]
    assert [row.ordinal for row in rows] == [1, 2]
    assert [row.id for row in passes[1]] == [row.id for row in first_pass]

    # And the answer given in the gap is still on question one.
    view = await requests_service.view(first_pass[0].id)
    assert view.answered_by is AnswerAuthor.user
    assert view.answer == "the answer"


async def test_a_retry_is_a_new_task_row_and_asks_afresh(harness, store: Store) -> None:
    """A second attempt row starts at ordinal 1 (06 §Restart durability).

    Re-execution of the *same* row replays; a retry or a rerun is a new
    row, and its questions are new questions — the answers of the attempt
    that failed may have been the reason it failed.
    """

    wf = Workflow(WORKFLOW)

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        await ctx.services.requests.reopen_or_create(
            "first?", mode=RequestMode.text, kind=RequestKind.question
        )
        if ctx.attempt == 1:
            raise RuntimeError("the answer was not the problem")

    harness.register(wf)
    run_id = await harness.submit(WORKFLOW)
    first = await harness.attempt()
    # The failure is retryable, so the runner enqueued attempt 2 as its
    # own row (04 §Failures) — which is what makes it ask again.
    second = await harness.attempt()
    assert second.task.id != first.task.id
    assert second.task.attempt == 2

    rows = await requests_of(store, run_id)
    assert [(row.task_id, row.ordinal) for row in rows] == [
        (first.task.id, 1),
        (second.task.id, 1),
    ]


async def test_the_counter_the_port_moves_is_the_contexts(harness) -> None:
    """``ctx.request_ordinal`` is what moved, and it is the attempt's.

    The body can read it, which is what makes the number the attempt's
    own bookkeeping rather than a secret of the port.
    """

    seen: list[int] = []
    wf = Workflow(WORKFLOW)

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        seen.append(ctx.request_ordinal)
        for prompt in ("a?", "b?"):
            await ctx.services.requests.reopen_or_create(
                prompt, mode=RequestMode.text, kind=RequestKind.question
            )
            seen.append(ctx.request_ordinal)

    harness.register(wf)
    await harness.submit(WORKFLOW)
    await harness.attempt()

    assert seen == [0, 1, 2]


# --------------------------------------------------------------------------
# The requests a node does not number
# --------------------------------------------------------------------------


async def test_an_agent_request_is_not_numbered(harness, store: Store) -> None:
    """Source ``agent``, no ordinal, and two of them do not collide.

    The unique index is on ``(task_id, ordinal)`` and partial, so two
    unnumbered requests on one task row are legal precisely because both
    ordinals are NULL — the storage half of "an agent's prompts are not
    replayable in position".
    """

    wf = Workflow(WORKFLOW)

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        await ctx.services.requests.create_agent_request(
            "may I write the file?",
            mode=RequestMode.options,
            kind=RequestKind.permission,
            options=OPTIONS,
            tool_call={"toolCallId": "call-1", "title": "write"},
        )
        await ctx.services.requests.create_agent_request(
            "may I run the tests?",
            mode=RequestMode.options,
            kind=RequestKind.permission,
            options=OPTIONS,
        )
        # A node question opened after them is still ordinal 1: the two
        # kinds of request do not share a counter.
        await ctx.services.requests.reopen_or_create(
            "and is that what you wanted?",
            mode=RequestMode.text,
            kind=RequestKind.question,
        )

    harness.register(wf)
    run_id = await harness.submit(WORKFLOW)
    await harness.attempt()

    rows = await requests_of(store, run_id)
    assert [(row.source, row.ordinal) for row in rows] == [
        (RequestSource.agent, None),
        (RequestSource.agent, None),
        (RequestSource.node, 1),
    ]
    assert rows[0].tool_call == {"toolCallId": "call-1", "title": "write"}
    assert rows[0].kind is RequestKind.permission
    assert rows[0].options == OPTIONS


# --------------------------------------------------------------------------
# Answering and waiting
# --------------------------------------------------------------------------


async def test_answer_as_engine_records_the_engine_as_the_author(
    harness, requests_service: RequestService
) -> None:
    """The headless fallback of 06 §Timeouts is legible as one afterwards."""

    wf = Workflow(WORKFLOW)
    answered: list[Any] = []

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        request = await ctx.services.requests.create_agent_request(
            "may I write the file?",
            mode=RequestMode.options,
            kind=RequestKind.permission,
            options=OPTIONS,
        )
        answered.append(await ctx.services.requests.answer_as_engine(request.id, "no"))

    harness.register(wf)
    await harness.submit(WORKFLOW)
    await harness.attempt()

    assert answered[0].author is AnswerAuthor.engine
    assert answered[0].option_id == "no"
    view = await requests_service.view(answered[0].request_id)
    assert view.answered_by is AnswerAuthor.engine
    assert view.answer == "no"


async def test_wait_returns_the_answer_and_claims_it(
    harness, requests_service: RequestService
) -> None:
    """``wait`` is the service's, and the port hands the id straight to it.

    The body parks, the operator answers, the body gets the value — and
    the answer is marked consumed, because this waiter took it. ``poll``
    is the other side of that: it re-delivers without claiming, which is
    what makes a reconnecting agent's second read free (08 §Agent).
    """

    wf = Workflow(WORKFLOW)
    opened: asyncio.Queue[int] = asyncio.Queue()
    got: list[Any] = []

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        request = await ctx.services.requests.reopen_or_create(
            "what shall I build?",
            mode=RequestMode.text,
            kind=RequestKind.question,
        )
        opened.put_nowait(request.id)
        got.append(await ctx.services.requests.wait(request.id, DEADLINE))

    harness.register(wf)
    run_id = await harness.submit(WORKFLOW)
    claimed = await harness.claim()
    attempt = harness.spawn(claimed[0])

    async with asyncio.timeout(DEADLINE):
        request_id = await opened.get()
        await requests_service.answer(request_id, value="a bridge")
        await attempt

    assert got[0].value == "a bridge"
    assert got[0].consumed is True

    port = TaskRequests(requests_service, run_id=run_id, task_id=claimed[0].task.id)
    polled = await port.poll(request_id, DEADLINE)
    assert polled is not None
    assert polled.value == "a bridge"


async def test_poll_gives_up_without_an_answer(
    harness, requests_service: RequestService
) -> None:
    """``None`` on expiry, and the request is left pending for the waiter."""

    wf = Workflow(WORKFLOW)
    polled: list[Any] = []

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        request = await ctx.services.requests.reopen_or_create(
            "what shall I build?",
            mode=RequestMode.text,
            kind=RequestKind.question,
        )
        polled.append(await ctx.services.requests.poll(request.id, 0.01))
        polled.append(request.id)

    harness.register(wf)
    await harness.submit(WORKFLOW)
    await harness.attempt()

    assert polled[0] is None
    view = await requests_service.view(polled[1])
    assert view.answered_by is None


async def test_wait_raises_when_nobody_answers(harness) -> None:
    """A timeout is not an answer: it reaches the body, which decides."""

    wf = Workflow(WORKFLOW)
    raised: list[Exception] = []

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        request = await ctx.services.requests.reopen_or_create(
            "what shall I build?",
            mode=RequestMode.text,
            kind=RequestKind.question,
        )
        try:
            await ctx.services.requests.wait(request.id, 0.01)
        except TimeoutError as exc:
            raised.append(exc)

    harness.register(wf)
    await harness.submit(WORKFLOW)
    await harness.attempt()

    assert raised


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


async def test_a_port_nothing_attached_refuses_to_number_a_question(
    store: Store, requests_service: RequestService
) -> None:
    """No context, no ordinal — and saying so beats counting from zero.

    A port that numbered from a counter of its own would re-attach every
    body to its first request forever.
    """

    async with store.uow() as uow:
        run = await uow.runs.insert(WORKFLOW, "a run")
        task = await uow.tasks.enqueue(run.id, "ask", None, priority=0, explicit=False)
    port = TaskRequests(requests_service, run_id=run.id, task_id=task.id)

    with pytest.raises(RuntimeError, match="not attached"):
        await port.reopen_or_create(
            "what shall I build?",
            mode=RequestMode.text,
            kind=RequestKind.question,
        )

    # The one opening that does not count needs no context.
    request = await port.create_agent_request(
        "may I?",
        mode=RequestMode.options,
        kind=RequestKind.permission,
        options=OPTIONS,
    )
    assert request.ordinal is None


async def test_a_port_belongs_to_one_attempt(harness) -> None:
    """Attaching twice is a defect, not a rebind.

    Two contexts sharing one port would have the second attempt's
    questions numbered from the first attempt's counter.
    """

    wf = Workflow(WORKFLOW)
    ports: list[TaskRequests] = []

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        assert isinstance(ctx.services.requests, TaskRequests)
        ports.append(ctx.services.requests)
        with pytest.raises(RuntimeError, match="already attached"):
            ctx.services.requests.attach(ctx)

    harness.register(wf)
    await harness.submit(WORKFLOW)
    await harness.attempt()

    assert ports


async def test_an_engine_without_a_request_service_asks_nobody_anything(
    unwired_harness, store: Store
) -> None:
    """The unwired port raises in the body rather than answering plausibly.

    An engine the composition root handed no request service cannot reach
    a person, and a body that tries finds out on the call rather than by
    receiving a default nobody gave.
    """

    wf = Workflow(WORKFLOW)
    raised: list[Exception] = []

    @wf.node(start=True)
    async def ask():
        ctx = current_task()
        try:
            await ctx.services.requests.reopen_or_create(
                "what shall I build?",
                mode=RequestMode.text,
                kind=RequestKind.question,
            )
        except NotImplementedError as exc:
            raised.append(exc)

    unwired_harness.register(wf)
    run_id = await unwired_harness.submit(WORKFLOW)
    await unwired_harness.attempt()

    assert "no request service" in str(raised[0])
    assert await requests_of(store, run_id) == []
