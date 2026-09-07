"""One attempt on the wire: its row, its submissions, its transcript (08 §Tasks).

:class:`TaskView` is the API's own model of a task rather than the store's
:class:`~athanore.store.rows.TaskRow`, and the reason is one field.
``TaskRow.token_hash`` is excluded from ``model_dump()``, which is the
store's guard; declaring a wire model that has no such field at all is a
second, independent one. A task token is header-only and appears in no
operator response (12 §Task tokens), and a rule that important is worth
holding in two places — one of which is the model OpenAPI is generated
from, so the field cannot even be *described* on the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from athanore.store import rows

__all__ = [
    "BranchFrame",
    "StreamChunk",
    "StreamOut",
    "SubmissionOut",
    "TaskDetail",
    "TaskView",
]


class BranchFrame(BaseModel):
    """One frame of a task's fan-out stack (04 §Branch frames).

    Frames nest, outermost first: a branch that fans out again pushes a
    second frame. ``key`` is the payload that branch was given, which is
    the branch's identity in every list the SPA groups by it.
    """

    fanout: int = Field(description="The task whose return value fanned out.")
    index: int = Field(description="This branch's zero-based index in that fan-out.")
    count: int = Field(description="How many branches that fan-out opened.")
    key: Any = Field(default=None, description="The payload this branch was given.")

    @classmethod
    def of(cls, frame: rows.BranchFrame) -> BranchFrame:
        return cls(
            fanout=frame.fanout, index=frame.index, count=frame.count, key=frame.key
        )


class TaskView(BaseModel):
    """One attempt of one node in one run. **Never** carries a token."""

    id: int = Field(description="The task id, unique across every run.")
    run_id: str = Field(description="The run this attempt belongs to.")
    node: str = Field(description="The node whose body this attempt runs.")
    attempt: int = Field(description="Which attempt of that node this row is, from 1.")
    status: rows.TaskStatus = Field(description="The task state machine of 03.")
    payload: Any = Field(
        default=None, description="The value the task was enqueued with."
    )
    result: Any = Field(
        default=None, description="What the body returned, once it has."
    )
    error: str | None = Field(
        default=None, description="Why the attempt failed, when it did."
    )
    priority: int = Field(description="The dispatch priority this attempt was given.")
    explicit: bool = Field(
        description="Whether that priority was declared on the node rather than "
        "defaulted."
    )
    stats: dict[str, Any] | None = Field(
        default=None,
        description="The agent's measurements for this attempt (05 §Stats entry); "
        "absent when nothing measured it.",
    )
    lineage: dict[str, Any] | None = Field(
        default=None,
        description="Where this attempt came from: its reason and its parent.",
    )
    terminal: bool = Field(
        description="Whether the attempt finished with no transition, making its "
        "`result` a branch output."
    )
    branch: list[BranchFrame] = Field(
        default_factory=list, description="The fan-out stack this attempt is inside."
    )
    created: datetime = Field(description="When the row was enqueued.")
    started: datetime | None = Field(default=None, description="When it was claimed.")
    finished: datetime | None = Field(default=None, description="When it ended.")

    @classmethod
    def of(cls, row: rows.TaskRow) -> TaskView:
        """The wire view of a stored task, with no token in it."""

        return cls(**cls._fields(row))

    @staticmethod
    def _fields(row: rows.TaskRow) -> dict[str, Any]:
        """The constructor arguments of ``row``, for this model and its
        subclass: :class:`TaskDetail` adds to them rather than round-tripping
        a built view through ``model_dump()``."""

        return dict(
            id=row.id,
            run_id=row.run_id,
            node=row.node,
            attempt=row.attempt,
            status=row.status,
            payload=row.payload,
            result=row.result,
            error=row.error,
            priority=row.priority,
            explicit=row.explicit,
            stats=row.stats,
            lineage=row.lineage,
            terminal=row.terminal,
            branch=[BranchFrame.of(frame) for frame in row.branch],
            created=row.created,
            started=row.started,
            finished=row.finished,
        )


class SubmissionOut(BaseModel):
    """One value an agent submitted for a task (03 §Submission)."""

    id: int = Field(description="The submission id.")
    task_id: int = Field(description="The attempt it was submitted for.")
    payload: Any = Field(default=None, description="The value, as it was accepted.")
    created: datetime = Field(description="When it was accepted.")

    @classmethod
    def of(cls, row: rows.SubmissionRow) -> SubmissionOut:
        return cls(
            id=row.id, task_id=row.task_id, payload=row.payload, created=row.created
        )


class TaskDetail(TaskView):
    """A task and the values submitted against it (08 §Tasks).

    The operator view: 08 overloads nothing by credential, so an agent
    reading its own task gets a different model on a different router
    (`/api/agent/`), and this one never has a token to omit.
    """

    submissions: list[SubmissionOut] = Field(
        default_factory=list, description="Every accepted submission, oldest first."
    )

    @classmethod
    def of_task(
        cls, row: rows.TaskRow, submissions: list[rows.SubmissionRow]
    ) -> TaskDetail:
        return cls(
            **cls._fields(row),
            submissions=[SubmissionOut.of(one) for one in submissions],
        )


class StreamChunk(BaseModel):
    """One segment of an agent transcript (05 §The ACP client)."""

    seq: int = Field(description="The per-task cursor `?after=` pages by.")
    kind: rows.ChunkKind = Field(description="What kind of segment this is.")
    text: str = Field(description="The segment itself.")
    created: datetime = Field(description="When it was recorded.")

    @classmethod
    def of(cls, row: rows.StreamChunkRow) -> StreamChunk:
        return cls(seq=row.seq, kind=row.kind, text=row.text, created=row.created)


class StreamOut(BaseModel):
    """A page of one task's transcript (08 §Tasks).

    ``last_seq`` is the highest sequence *stored* for the task, not the
    highest in this page, so a client that has caught up can tell. ``live``
    says the attempt is still running — ``in_progress`` or ``waiting``,
    because a waiting attempt goes on writing once its request is
    answered — which is what stops the SPA polling a transcript that will
    never grow again.
    """

    chunks: list[StreamChunk] = Field(description="The page, in sequence order.")
    last_seq: int = Field(description="The highest sequence stored for this task.")
    live: bool = Field(
        description="Whether the attempt is still running (`in_progress` or "
        "`waiting`), so the transcript may still grow."
    )
