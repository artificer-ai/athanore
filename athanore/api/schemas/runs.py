"""A run on the wire: the list row, the detail, and its work log (08 §Runs).

Two views again, and the split is the one 08 draws. :class:`RunSummary` is
what the run list shows — enough to render a row and nothing that costs a
second query — and :class:`RunDetail` adds what the overview pane needs:
the description, the run's output, its tasks and its agent totals.

``output`` and ``outputs`` are the same fact twice, on purpose (D58).
``output`` follows the shape rule of 04 §Routing edge cases — one value
when a single terminal task ended the run, a list in branch order when
several branches terminated independently — and ``outputs`` is *always* a
list, one entry per terminal task, so a consumer that wants the
per-branch view never has to inspect the shape of the other.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from athanore.api.schemas.tasks import TaskView
from athanore.store import rows

__all__ = [
    "BranchRef",
    "LogEntry",
    "PositionOut",
    "RunDetail",
    "RunOutput",
    "RunStats",
    "RunSummary",
]


class RunSummary(BaseModel):
    """One row of the run list (08 §Runs).

    ``current_nodes`` is plural because a fan-out puts a run in several
    nodes at once. ``unregistered`` is not stored: it says this server has
    no workflow of that name registered, so the run is shown but nothing
    will dispatch it (03 §Run).
    """

    id: str = Field(description="The run id, a ULID.")
    workflow: str = Field(description="The workflow this run executes.")
    title: str = Field(description="The operator's title for the run.")
    status: rows.RunStatus = Field(description="The run state machine of 03.")
    position: int = Field(
        description="The run's place in the dispatch list; runs are numbered "
        "1..n in list order."
    )
    current_nodes: list[str] = Field(
        default_factory=list,
        description="The nodes with an in-progress or waiting attempt right now.",
    )
    pending_requests: int = Field(
        default=0, description="Unanswered, non-stale requests waiting on a person."
    )
    created: datetime = Field(description="When the run was submitted.")
    updated: datetime = Field(description="When anything about it last changed.")
    unregistered: bool = Field(
        default=False,
        description="Whether this server has no workflow of that name registered.",
    )

    @classmethod
    def of(cls, row: rows.RunSummary) -> RunSummary:
        """The wire view of a run-list row."""

        return cls(**cls._fields(row))

    @staticmethod
    def _fields(row: rows.RunSummary) -> dict[str, Any]:
        """The constructor arguments of ``row``, shared with :class:`RunDetail`."""

        return dict(
            id=row.id,
            workflow=row.workflow,
            title=row.title,
            status=row.status,
            position=row.position,
            current_nodes=list(row.current_nodes),
            pending_requests=row.pending_requests,
            created=row.created,
            updated=row.updated,
            unregistered=row.unregistered,
        )


class BranchRef(BaseModel):
    """Which branch an output came out of (D58).

    The index and the key of each frame, and not the frame's ``fanout`` or
    ``count``: an output names its branch so a consumer can group by it,
    and the task it came from is in the same entry for anything more.
    """

    index: int = Field(description="The branch's zero-based index in its fan-out.")
    key: Any = Field(default=None, description="The payload that branch was given.")


class RunOutput(BaseModel):
    """One terminal task's value, with the branch it came out of (D58)."""

    task_id: int = Field(description="The terminal attempt that produced it.")
    node: str = Field(description="The node that attempt ran.")
    branch: list[BranchRef] = Field(
        default_factory=list,
        description="The fan-out stack the attempt was inside, outermost first; "
        "empty for a run that never fanned out.",
    )
    value: Any = Field(default=None, description="What the body returned.")

    @classmethod
    def of(cls, task: rows.TaskRow) -> RunOutput:
        """The output entry of one terminal task."""

        return cls(
            task_id=task.id,
            node=task.node,
            branch=[
                BranchRef(index=frame.index, key=frame.key) for frame in task.branch
            ],
            value=task.result,
        )


class RunStats(BaseModel):
    """A run's agent totals, summed over its attempts (05 §Stats).

    Every field is optional and nothing is zero-filled: a provider that
    reported no cost leaves ``cost`` absent rather than claiming zero (01
    §Real data only). ``duration_s`` is the sum of the attempts' durations
    and not wall-clock time, which fan-out would make meaningless.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    tool_calls: int | None = None
    duration_s: float | None = None

    @classmethod
    def of(cls, stats: rows.RunStats) -> RunStats:
        return cls(**stats.model_dump())


class RunDetail(RunSummary):
    """A run, its tasks and its totals (08 §Runs)."""

    description: str = Field(default="", description="The operator's description.")
    output: Any = Field(
        default=None,
        description="The run's output: one value for a single terminal task, a "
        "list in branch order when several branches terminated (D58). Null "
        "before the run ends, and also when it ended by returning null.",
    )
    outputs: list[RunOutput] = Field(
        default_factory=list,
        description="One entry per terminal task, always a list (D58).",
    )
    tasks: list[TaskView] = Field(
        default_factory=list, description="Every attempt of the run, oldest first."
    )
    stats: RunStats = Field(
        default_factory=lambda: RunStats(),
        description="The agent totals of the run.",
    )

    @classmethod
    def of_run(
        cls,
        row: rows.RunSummary,
        *,
        tasks: list[rows.TaskRow],
        stats: rows.RunStats,
        outputs: list[RunOutput] | None = None,
    ) -> RunDetail:
        """The wire view of a run and everything under it.

        Named apart from :meth:`RunSummary.of` rather than overriding it:
        a detail needs the tasks and the totals a summary does not, and a
        classmethod that widened its base's signature would be a lie to
        every caller holding a ``RunSummary``.

        ``outputs`` defaults to the entries of the terminal tasks in
        ``tasks``, which is what 08 §Runs says it is; a caller that
        already computed them passes them rather than having them derived
        twice.
        """

        if outputs is None:
            outputs = [RunOutput.of(task) for task in tasks if task.terminal]
        return cls(
            **cls._fields(row),
            description=row.description,
            output=row.output,
            outputs=outputs,
            tasks=[TaskView.of(task) for task in tasks],
            stats=RunStats.of(stats),
        )


class LogEntry(BaseModel):
    """One entry of a run's work log, append-only (03).

    The work log is the inter-stage channel (D4): the engine's failures,
    the operator's notes and every agent deliverable, in one ordered list.
    ``kind`` is absent on a plain entry.
    """

    id: int = Field(description="The entry id; the log is ordered by it.")
    run_id: str = Field(description="The run the entry belongs to.")
    task_id: int | None = Field(
        default=None, description="The attempt that wrote it, when one did."
    )
    node: str = Field(
        description="The node it was written under; `user` for an operator note "
        "with no node in flight."
    )
    author: rows.LogAuthor = Field(description="Who wrote it.")
    kind: rows.LogKind | None = Field(
        default=None, description="What it is, for filtering; absent on a plain entry."
    )
    text: str = Field(description="The entry itself, never truncated.")
    created: datetime = Field(description="When it was written.")

    @classmethod
    def of(cls, row: rows.LogEntryRow) -> LogEntry:
        return cls(
            id=row.id,
            run_id=row.run_id,
            task_id=row.task_id,
            node=row.node,
            author=row.author,
            kind=row.kind,
            text=row.text,
            created=row.created,
        )


class PositionOut(BaseModel):
    """Where a run sits in the dispatch list after a move (D57)."""

    position: int = Field(
        description="The run's place in the dispatch list after the move, "
        "numbered from 1. The `index` that asked for it is zero-based (D57)."
    )
