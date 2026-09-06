"""The request repository: the human-in-the-loop channel's storage.

06 §The model is the vocabulary — a request, at most one answer, keyed by
the request because an answer without its request does not exist — and
this module is where it is written and read. It stores and reads; it
decides nothing. Validating an answer against the request's mode,
claiming it for the waiter, mapping a collision onto an error code: all
of that is the request *service*, a tier up.

Three things are worth stating once, here:

- **A second answer raises.** The primary key on ``answers.request_id``
  is what makes "one answer per request, claimed exactly once" a fact of
  the database rather than a convention, so :meth:`RequestRepo.answer`
  lets the :exc:`~sqlalchemy.exc.IntegrityError` out. The service turns
  it into ``already_answered`` (409); swallowing it here would lose the
  race the constraint exists to detect.

- **Pending is not "unanswered".** An unanswered request whose task is no
  longer ``in_progress`` or ``waiting`` is *stale*: the attempt that
  asked it is gone, so nobody will ever consume an answer to it, and it
  must leave the operator's inbox instead of sitting there forever (06
  §Restart durability). The two flags are computed in the join, which is
  also what makes ``pending_only`` a predicate rather than a filter
  applied to rows already fetched.

- **One query, three tables.** :meth:`RequestRepo.view` and
  :meth:`RequestRepo.list_views` are the same statement
  (:func:`view_statement`) with different predicates:
  ``requests ⟕ answers ⟗ tasks``, an outer join to the answer that may
  not exist and an inner join to the task that always does.

``age`` is finished in Python. It is ``now - created``, and the two
backends spell date arithmetic differently enough (``julianday`` against
``EXTRACT(EPOCH FROM …)``) that computing it in SQL would be a dialect
switch buying nothing: the row already carries ``created``, and one
timestamp is taken per call so every view in a listing is measured
against the same instant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import RowMapping, Select, and_, not_, select

from athanore.store.clock import now
from athanore.store.repos.base import Repo, aware
from athanore.store.rows import AnswerRow, RequestRow, RequestView, TaskStatus
from athanore.store.tables import answers, requests, tasks

#: The task statuses under which a request is still worth answering: the
#: body that asked is running, or parked in ``human_input`` waiting for
#: this very answer (06 §Service). The same pair means something else
#: elsewhere — the nodes a run is "currently" at, the attempts recovery
#: resets — so each module names it for what it means there.
ANSWERABLE: tuple[str, str] = (
    TaskStatus.in_progress.value,
    TaskStatus.waiting.value,
)

#: The label the answer's ``option_id`` and ``value`` are selected under.
#: ``requests`` has neither column, so nothing collides; they are folded
#: into the single ``answer`` field of 08 §Requests when the view is
#: built.
_ANSWER_OPTION_ID = "answer_option_id"
_ANSWER_VALUE = "answer_value"


def view_statement(
    run_id: str | None = None, pending_only: bool = False
) -> Select[Any]:
    """The joined read of 08 §Requests: a request, its answer, its node.

    ``requests ⟕ answers ⟗ tasks``. ``pending`` and ``stale`` are computed
    here rather than after the fetch, so ``pending_only`` narrows the
    query instead of the result.

    The order is the order the requests were asked, oldest first. 06's two
    surfaces sort differently — the run's pane puts pending first, the
    global pane newest first — so the store hands out one deterministic
    order and neither presentation is baked into it.
    """

    unanswered = answers.c.request_id.is_(None)
    live = tasks.c.status.in_(ANSWERABLE)
    pending = and_(unanswered, live)
    # `answer IS NULL AND NOT pending`, which with `unanswered` already
    # asserted is `answer IS NULL AND NOT live`. `tasks.status` is NOT
    # NULL, so there is no third truth value to fall through.
    stale = and_(unanswered, not_(live))

    statement = (
        select(
            requests.c.id,
            requests.c.run_id,
            requests.c.task_id,
            requests.c.prompt,
            requests.c.mode,
            requests.c.source,
            requests.c.kind,
            requests.c.options,
            requests.c["schema"],
            requests.c.tool_call,
            requests.c.created,
            tasks.c.node.label("node"),
            answers.c.option_id.label(_ANSWER_OPTION_ID),
            answers.c.value.label(_ANSWER_VALUE),
            answers.c.author.label("answered_by"),
            pending.label("pending"),
            stale.label("stale"),
        )
        .select_from(
            requests.join(tasks, tasks.c.id == requests.c.task_id).outerjoin(
                answers, answers.c.request_id == requests.c.id
            )
        )
        .order_by(requests.c.id)
    )
    if run_id is not None:
        statement = statement.where(requests.c.run_id == run_id)
    if pending_only:
        statement = statement.where(pending)
    return statement


def _age(created: object, stamp: datetime) -> float:
    """Seconds between ``created`` and ``stamp``.

    ``created`` comes back naive from SQLite and aware from PostgreSQL
    (D87), so it is made aware before the subtraction rather than after —
    :meth:`Repo._row` would otherwise only fix the copy it validates.
    """

    when = aware(created)
    if not isinstance(when, datetime):  # pragma: no cover - the column is a timestamp
        raise TypeError(f"requests.created is not a timestamp: {created!r}")
    return (stamp - when).total_seconds()


class RequestRepo(Repo):
    """Queries over ``requests`` and ``answers`` (07 §Schema)."""

    async def create(
        self,
        run_id: str,
        task_id: int,
        prompt: str,
        *,
        mode: str,
        source: str,
        kind: str,
        options: list[dict[str, Any]] | None = None,
        schema: dict[str, Any] | None = None,
        tool_call: dict[str, Any] | None = None,
        ordinal: int | None = None,
    ) -> RequestRow:
        """Open a request against one task attempt.

        ``ordinal`` numbers the node-raised requests of that attempt so a
        body re-executing after a restart re-attaches to the one it
        already asked (06 §Restart durability); it is ``None`` for the
        agent-raised ones, of which an attempt may have any number. A
        second request at the same ``(task_id, ordinal)`` raises
        :exc:`~sqlalchemy.exc.IntegrityError` — the partial unique index of
        07 §Schema — because reusing one is ``reopen``'s job, a tier up,
        not a write that silently duplicates it.
        """

        result = await self.conn.execute(
            requests.insert()
            .values(
                run_id=run_id,
                task_id=task_id,
                ordinal=ordinal,
                prompt=prompt,
                mode=str(mode),
                source=str(source),
                kind=str(kind),
                options=options,
                schema=schema,
                tool_call=tool_call,
                created=now(),
            )
            .returning(*requests.c)
        )
        row = self._first(RequestRow, result)
        if row is None:  # pragma: no cover - an INSERT ... RETURNING has a row
            raise RuntimeError("the request insert returned no row")
        return row

    async def get(self, request_id: int) -> RequestRow | None:
        """One request, or ``None``."""

        result = await self.conn.execute(
            select(requests).where(requests.c.id == request_id)
        )
        return self._first(RequestRow, result)

    async def by_ordinal(self, task_id: int, ordinal: int) -> RequestRow | None:
        """The request this attempt asked at ``ordinal``, or ``None``.

        What a recovered body reads before asking again: an existing row
        is reused — answered, the answer replays; pending, the body parks
        on it — and only a gap opens a new request (06 §Restart
        durability).
        """

        result = await self.conn.execute(
            select(requests).where(
                requests.c.task_id == task_id,
                requests.c.ordinal == ordinal,
            )
        )
        return self._first(RequestRow, result)

    async def answer(
        self,
        request_id: int,
        author: str,
        option_id: str | None = None,
        value: Any = None,
    ) -> AnswerRow:
        """Record the one answer a request may have.

        ``option_id`` is what an ``options`` request is answered with and
        ``value`` what a ``text`` or ``form`` one is; which of them is
        required is the mode's rule, checked by the service where the
        answer lands (06 §Service).

        A second answer raises :exc:`~sqlalchemy.exc.IntegrityError` on
        the primary key, and so does an answer to a request that does not
        exist, on the foreign key. Neither is caught here: both are
        answers the caller must be told did not land, and the service maps
        the first to ``already_answered``.
        """

        result = await self.conn.execute(
            answers.insert()
            .values(
                request_id=request_id,
                author=str(author),
                option_id=option_id,
                value=value,
                consumed=False,
                created=now(),
            )
            .returning(*answers.c)
        )
        row = self._first(AnswerRow, result)
        if row is None:  # pragma: no cover - an INSERT ... RETURNING has a row
            raise RuntimeError("the answer insert returned no row")
        return row

    async def mark_consumed(self, request_id: int) -> AnswerRow | None:
        """Flag this request's answer as taken by its waiter; ``None`` if
        there is none.

        The flag records that a waiter claimed the answer (06 §The model).
        It is informational on a replay — a body re-executing on the same
        task row is not a second waiter — so marking an answer that is
        already consumed is not an error and writes ``consumed`` again.
        """

        result = await self.conn.execute(
            answers.update()
            .where(answers.c.request_id == request_id)
            .values(consumed=True)
            .returning(*answers.c)
        )
        return self._first(AnswerRow, result)

    async def view(self, request_id: int) -> RequestView | None:
        """One request as 08 §Requests shows it, or ``None``."""

        statement = view_statement().where(requests.c.id == request_id)
        result = await self.conn.execute(statement)
        mapping = result.mappings().first()
        return None if mapping is None else self._view(mapping, now())

    async def list_views(
        self, run_id: str | None = None, pending_only: bool = False
    ) -> list[RequestView]:
        """The requests of a run, or of every run, oldest first.

        ``pending_only`` is the inbox of 08 §Requests
        (``GET /api/requests?pending=true``): it excludes the answered
        **and** the stale, so what is left is exactly the requests a
        person can still act on.
        """

        result = await self.conn.execute(view_statement(run_id, pending_only))
        stamp = now()
        return [self._view(mapping, stamp) for mapping in result.mappings()]

    def _view(self, mapping: RowMapping, stamp: datetime) -> RequestView:
        """One :class:`RequestView` from one row of :func:`view_statement`.

        The answer's two columns fold into the single ``answer`` field of
        08: an ``options`` request is answered by id and the other two
        modes by value, and a request with no answer has neither.
        """

        fields = dict(mapping)
        option_id = fields.pop(_ANSWER_OPTION_ID)
        value = fields.pop(_ANSWER_VALUE)
        fields["answer"] = value if option_id is None else option_id
        fields["age"] = _age(fields["created"], stamp)
        return self._row(RequestView, fields)


__all__ = ["ANSWERABLE", "RequestRepo", "view_statement"]
