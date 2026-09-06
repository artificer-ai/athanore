"""The request channel's service: open one, answer it once, wait for it.

06 §Service is the specification and this module is all of it. A request
is opened by whoever is about to block on a person — a node body through
``human_input``, the ACP bridge on a permission or an elicitation, an
agent through the HTTP ask — and from that moment exactly two things can
happen to it: somebody answers it, or its task ends and it goes stale.

Three properties carry the module.

- **One answer, claimed once.** The primary key on ``answers.request_id``
  is the mechanism; :meth:`RequestService.answer` reads the request first
  only so that the second answer gets a sentence rather than a database
  error, and maps the :exc:`~sqlalchemy.exc.IntegrityError` onto the same
  :exc:`~athanore.requests.errors.AlreadyAnswered` when two answers race
  past that read. The constraint is the guard; the pre-check is the
  manners.

- **Validation happens where the answer lands.** The mode decides the
  shape — an offered ``option_id``, a non-empty string, an object — and a
  ``form`` request may have a validator registered by the waiter that
  opened it (:mod:`athanore.requests.validators`). What the validator
  returns is what is stored, so an answer is normalised once, at the door,
  and every later reader sees the normalised form.

- **A waiter subscribes before it reads.** The store commits and *then*
  publishes (07 §Unit of work and outbox), so a subscription taken before
  the store is consulted can see an answer twice but can never miss one.
  Taken the other way round, an answer landing between the read and the
  subscription is a waiter parked forever on a question that has already
  been answered. :meth:`RequestService.wait` and
  :meth:`RequestService.poll` therefore subscribe on their first line.

Nothing here moves a task. Releasing the node's pool slot around the wait
is the engine's (``ctx.services.lease.released``, 04 §Waiting), and
routing on the answer is the body's: an answer is a value, and a value
cannot move the graph (06 §The model).
"""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from athanore.events.bus import EventBus, Subscription
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.events.payloads import RequestAnswered, RequestOpened
from athanore.requests.errors import (
    AlreadyAnswered,
    InvalidAnswer,
    InvalidOption,
    RequestNotFound,
    StaleRequest,
)
from athanore.requests.validators import Validator, json_schema_validator
from athanore.store.clock import now
from athanore.store.rows import (
    AnswerAuthor,
    AnswerRow,
    RequestKind,
    RequestMode,
    RequestRow,
    RequestSource,
    RequestView,
)
from athanore.store.uow import Store


class RequestService:
    """The human-in-the-loop channel, over one store and one bus.

    One instance per process, constructed beside the engine: the
    registered validators are in-memory state belonging to the waiters
    alive in *this* process, and a second instance would be a second set
    of them (06 §Restart durability is the same fact stated across a
    restart — a validator does not survive one, and the answer given in
    the gap is re-validated on replay).
    """

    def __init__(self, store: Store, bus: EventBus) -> None:
        self._store = store
        self._bus = bus
        #: The callable a ``form`` request's waiter registered, by request
        #: id. Empty for every other mode, and empty after a restart.
        self._validators: dict[int, Validator] = {}

    # ----------------------------------------------------------------
    # Opening
    # ----------------------------------------------------------------

    async def create(
        self,
        run_id: str,
        task_id: int,
        prompt: str,
        *,
        mode: RequestMode,
        source: RequestSource,
        kind: RequestKind,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        tool_call: dict[str, Any] | None = None,
        ordinal: int | None = None,
    ) -> RequestRow:
        """Open a request against ``task_id`` and announce it.

        One transaction: the row and its ``request.opened``, so a
        subscriber that fetches on receipt finds the request it was told
        about (03 invariant 7).

        An ``options`` request with nothing to choose from is refused
        here rather than written: :meth:`answer` accepts only an offered
        ``option_id``, so such a row is a question no answer can satisfy,
        and the honest place to say so is the call that would create it
        (D115).

        The event's ``node`` comes from the task the request was opened
        against. It is read after the insert on purpose — the foreign key
        on ``requests.task_id`` has already refused an unknown task by
        then, so this is a lookup and not a second check.
        """

        if mode is RequestMode.options and not options:
            raise ValueError(
                "an `options` request needs the options it offers: "
                "`answer` accepts only an option_id the request listed"
            )
        async with self._store.uow() as uow:
            request = await uow.requests.create(
                run_id,
                task_id,
                prompt,
                mode=mode,
                source=source,
                kind=kind,
                options=options,
                schema=schema,
                tool_call=tool_call,
                ordinal=ordinal,
            )
            task = await uow.tasks.get(task_id)
            if task is None:  # pragma: no cover - the FK refused it above
                raise RuntimeError(f"request {request.id} names no task")
            uow.emit(
                Event(
                    run_id=run_id,
                    task_id=task_id,
                    name=EventName.request_opened,
                    data=RequestOpened(
                        request_id=request.id,
                        mode=request.mode.value,
                        kind=request.kind.value,
                        source=request.source.value,
                        node=task.node,
                        ordinal=request.ordinal,
                    ).model_dump(),
                    created=now(),
                )
            )
        return request

    async def reopen(self, task_id: int, ordinal: int) -> RequestRow | None:
        """The request this task row asked at ``ordinal``, or ``None``.

        What a body re-executed after a restart reads before it asks
        again (04 §Waiting, 06 §Restart durability): an existing row is
        reused whether or not it is answered — answered, the answer
        replays; pending, the body parks on it — and only a gap means the
        question has not been asked yet. ``consumed`` is informational
        here: a replay on the same task row is not a second waiter.
        """

        async with self._store.reader() as reader:
            return await reader.requests.by_ordinal(task_id, ordinal)

    # ----------------------------------------------------------------
    # Answering
    # ----------------------------------------------------------------

    def register_validator(self, request_id: int, fn: Validator) -> None:
        """Validate this request's answer with ``fn`` when it lands.

        Registered by whoever opened the request, because only they know
        what the answer is for: ``human_input(output_model=M)`` registers
        :func:`~athanore.requests.validators.pydantic_validator`, and the
        ACP bridge and the HTTP ask register
        :func:`~athanore.requests.validators.json_schema_validator` over
        the schema they were handed (06 §Service) —
        :meth:`register_schema_validator` is the second of those two, said
        in one call.

        Only ``form`` answers are passed through it. The other two modes
        have their shape fixed by the mode itself.
        """

        self._validators[request_id] = fn

    def register_schema_validator(
        self, request_id: int, schema: dict[str, Any]
    ) -> None:
        """Validate this request's answer against the JSON schema ``schema``.

        :meth:`register_validator` for the registrant that has a schema
        and no way to build a callable from it: the ACP elicitation bridge
        (``athanore.agents.policies``, 05 §Policies) and the HTTP ask both
        carry a document an agent wrote, and ``athanore.agents`` may not
        import this package to turn one into a validator (02 §Layering,
        D123). Building it here costs a line and keeps the arrow undrawn.
        """

        self.register_validator(request_id, json_schema_validator(schema))

    def unregister_validator(self, request_id: int) -> None:
        """Forget this request's validator. Not registering one is fine.

        Called when the waiter goes away, answered or not, so a run's
        finished requests do not keep their closures alive for the life
        of the process.
        """

        self._validators.pop(request_id, None)

    async def answer(
        self,
        request_id: int,
        *,
        option_id: str | None = None,
        value: Any = None,
        author: AnswerAuthor = AnswerAuthor.user,
    ) -> AnswerRow:
        """Record the one answer ``request_id`` may have.

        The refusals, in the order they are decided:

        - :exc:`~athanore.requests.errors.RequestNotFound` — no such
          request;
        - :exc:`~athanore.requests.errors.AlreadyAnswered` — it has an
          answer already;
        - :exc:`~athanore.requests.errors.StaleRequest` — it has none and
          its task has ended, so nobody is left to consume one;
        - :exc:`~athanore.requests.errors.InvalidOption` — the mode is
          ``options`` and ``option_id`` is not one it offered;
        - :exc:`~athanore.requests.errors.InvalidAnswer` — the mode is
          ``text`` and the answer is not a non-empty string, or the mode
          is ``form`` and the answer is not an object or was refused by
          the registered validator.

        The row and its ``request.answered`` go in one transaction. A
        second answer that gets past the read above collides on the
        primary key, and that collision is the same refusal: the
        constraint is what makes "one answer per request" true, and this
        method is what makes it a sentence.
        """

        author = AnswerAuthor(author)
        view = await self.view(request_id)
        if view.answered_by is not None:
            raise AlreadyAnswered(
                f"request {request_id} was already answered by {view.answered_by.value}"
            )
        if not view.pending:
            raise StaleRequest(
                f"request {request_id} is stale: task {view.task_id} "
                f"({view.node}) is no longer running, so nothing will read "
                "an answer to it"
            )
        chosen, stored = self._checked(view, option_id, value)

        try:
            async with self._store.uow() as uow:
                answer = await uow.requests.answer(
                    request_id,
                    author=author.value,
                    option_id=chosen,
                    value=stored,
                )
                uow.emit(
                    Event(
                        run_id=view.run_id,
                        task_id=view.task_id,
                        name=EventName.request_answered,
                        data=RequestAnswered(
                            request_id=request_id,
                            author=author.value,
                            option_id=chosen,
                        ).model_dump(),
                        created=now(),
                    )
                )
        except IntegrityError as exc:
            # The unique constraint on `answers.request_id`: another
            # answer landed between the read above and this insert. The
            # pre-check is a nicer message, never the guard.
            raise AlreadyAnswered(
                f"request {request_id} was answered while this answer was "
                "being validated"
            ) from exc
        return answer

    def _checked(
        self, view: RequestView, option_id: str | None, value: Any
    ) -> tuple[str | None, Any]:
        """The ``(option_id, value)`` to store, or the refusal.

        Each mode keeps exactly one of the two columns, so a row never
        carries an answer in a shape its request did not ask for: an
        ``options`` answer is an id, a ``text`` and a ``form`` answer is a
        value, and whatever was passed in the other slot is not written.
        """

        if view.mode is RequestMode.options:
            offered = [
                option.get("option_id")
                for option in view.options or []
                if isinstance(option, dict)
            ]
            if option_id is None or option_id not in offered:
                raise InvalidOption(
                    f"{option_id!r} is not an option of request {view.id}; "
                    f"it offers {offered}"
                )
            return option_id, None

        if view.mode is RequestMode.text:
            if not isinstance(value, str) or not value.strip():
                raise InvalidAnswer(
                    f"request {view.id} is a `text` request: its answer must "
                    "be a non-empty string"
                )
            return None, value

        if not isinstance(value, dict):
            raise InvalidAnswer(
                f"request {view.id} is a `form` request: its answer must be an object"
            )
        validator = self._validators.get(view.id)
        if validator is None:
            # No waiter registered one: the object shape is the whole
            # contract, and the schema on the row is documentation the
            # SPA renders a form from (06 §Service).
            return None, value
        return None, _storable(validator(value))

    # ----------------------------------------------------------------
    # Waiting
    # ----------------------------------------------------------------

    async def wait(
        self,
        request_id: int,
        timeout: float | None = None,  # noqa: ASYNC109 - see the docstring
    ) -> AnswerRow:
        """Block until ``request_id`` is answered, and claim the answer.

        The claim is ``RequestRepo.mark_consumed``: this waiter took it.
        It is made after the wait rather than inside it, so a timeout
        firing on the last statement cannot leave an answer marked as
        taken by a waiter that raised.

        Raises :exc:`TimeoutError` when ``timeout`` elapses first,
        leaving the request pending — a wait that gave up is not an
        answer, and 04 §Waiting hands the exception to the node body,
        which decides. ``timeout=None`` waits indefinitely, and an id
        that names no request raises
        :exc:`~athanore.requests.errors.RequestNotFound` rather than
        waiting for an answer nothing can give.

        ASYNC109 would have the caller wrap this in
        :func:`asyncio.timeout`. It cannot: the wait has to end *and* the
        request stay answerable for whoever asks next, and a scope around
        the call would cancel the claim as readily as the wait.
        """

        answer = await self._await_answer(request_id, timeout)
        if answer is None:
            raise TimeoutError(
                f"request {request_id} was not answered within {timeout}s"
            )
        async with self._store.uow() as uow:
            claimed = await uow.requests.mark_consumed(request_id)
        # The answer was read a moment ago and answers are never deleted
        # while their request lives, so the update matched.
        return claimed if claimed is not None else answer

    async def poll(self, request_id: int, wait_s: float) -> AnswerRow | None:
        """The answer to ``request_id``, waiting up to ``wait_s`` for one.

        ``None`` when the wait expires, and ``wait_s=0`` is the answer
        as the store has it now. The agent long-poll of 08
        (``GET /api/agent/tasks/{id}/requests/{rid}?wait=N``): the caller
        is not the waiter that opened the request, so nothing is claimed
        and re-delivery is idempotent — a reconnecting agent asking twice
        gets the same answer twice, which is what makes a dropped
        connection cost nothing. An id that names no request raises
        :exc:`~athanore.requests.errors.RequestNotFound`, which is the
        404 the endpoint above it owes the agent.
        """

        return await self._await_answer(request_id, wait_s)

    async def _await_answer(
        self,
        request_id: int,
        timeout: float | None,  # noqa: ASYNC109 - this *is* the wrapper
    ) -> AnswerRow | None:
        """The answer, or ``None`` if ``timeout`` elapsed. The wake-up guard.

        Subscribe, *then* read the store. The store publishes after it
        commits, so the only event this ordering can produce twice is one
        whose answer the first read already found; the other ordering
        drops the answer that lands in between and parks forever (06
        §Wake-ups).

        The loop re-reads the store rather than trusting the event's
        payload, because ``request.answered`` deliberately does not carry
        the value (18 §Requests): it may be large, or sensitive, and the
        row is the one copy of it.

        An id that names no request raises
        :exc:`~athanore.requests.errors.RequestNotFound` instead of
        waiting out the timeout, because nothing will ever answer it: a
        wait that ends in ``TimeoutError`` says "no one answered yet",
        which is a different and misleading thing to tell the caller.
        """

        if timeout is not None and timeout <= 0:
            # "How long may I wait" of nothing is "is there an answer
            # right now": one read, no subscription. It cannot be left to
            # `asyncio.timeout(0)` below, whose deadline has passed before
            # the loop runs — the read itself would be cancelled, and the
            # caller would be told "not answered yet" about an answer that
            # is in the store. `human_input` asks exactly this question of
            # a request it re-attached to after a restart, and the agent
            # long-poll asks it as `?wait=0`.
            await self.view(request_id)
            return await self._stored_answer(request_id)

        subscription = self._bus.subscribe([EventName.request_answered])
        try:
            async with asyncio.timeout(timeout):
                await self.view(request_id)
                while True:
                    answer = await self._stored_answer(request_id)
                    if answer is not None:
                        return answer
                    await self._woken(subscription, request_id)
        except TimeoutError:
            return None
        finally:
            subscription.close()

    @staticmethod
    async def _woken(subscription: Subscription, request_id: int) -> None:
        """Return once an event arrives that could be this answer.

        That is an ``request.answered`` naming ``request_id`` — or any of
        them at all once this subscription has overflowed, because one of
        the events the bus dropped for it may have been the one. The
        caller re-reads the store either way, so a spurious wake-up costs
        one indexed read and a missed one would cost the whole wait.
        """

        while True:
            event = await subscription.queue.get()
            if event.data.get("request_id") == request_id:
                return
            if subscription.overflowed:
                return

    async def _stored_answer(self, request_id: int) -> AnswerRow | None:
        """This request's answer as the store has it, or ``None``."""

        async with self._store.reader() as reader:
            return await reader.requests.get_answer(request_id)

    # ----------------------------------------------------------------
    # Reading
    # ----------------------------------------------------------------

    async def view(self, request_id: int) -> RequestView:
        """One request with its answer and its node (08 §Requests).

        Raises :exc:`~athanore.requests.errors.RequestNotFound` rather
        than returning ``None``: an id came from somewhere, and every
        surface that reads one — the endpoint, the CLI, :meth:`answer` —
        has to say so when it resolves to nothing.
        """

        async with self._store.reader() as reader:
            view = await reader.requests.view(request_id)
        if view is None:
            raise RequestNotFound(f"no request {request_id}")
        return view

    async def list_for_run(self, run_id: str) -> list[RequestView]:
        """Every request of ``run_id``, answered and pending, oldest first."""

        async with self._store.reader() as reader:
            return await reader.requests.list_views(run_id)

    async def inbox(self) -> list[RequestView]:
        """Every pending request across every run (the attention surface).

        Pending, not merely unanswered: a request whose task has ended is
        stale and leaves the inbox, because answering it would reach
        nobody (06 §Restart durability).
        """

        async with self._store.reader() as reader:
            return await reader.requests.list_views(None, pending_only=True)


def _storable(value: Any) -> Any:
    """What a validator returned, in a shape ``answers.value`` can hold.

    ``answers.value`` is JSON, and
    :func:`~athanore.requests.validators.pydantic_validator` returns the
    model *instance* — the thing ``human_input(output_model=M)`` promises
    the body. The instance cannot be stored, so it is dumped in JSON mode
    here and the body re-validates on the way out (D115). Anything else a
    validator returns is stored as it came back.
    """

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


__all__ = ["RequestService"]
