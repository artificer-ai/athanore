"""The small acknowledgements every operator router answers with (08).

Four one-field models rather than one loose ``{"id": …}``: 08 §Endpoints
names the key each route returns — ``run_id``, ``task_id``, ``log_id``,
``position`` — and the generated TypeScript client is only as useful as
the name it hands the SPA. A single shared model with four optional ids
would type every one of them as "maybe absent" and make the caller check
what the contract already fixes.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["Created", "LogRef", "Ok", "TaskRef"]


class Ok(BaseModel):
    """An operation that succeeded and has nothing else to report.

    ``note`` is the one place a router adds a sentence about *how* it
    succeeded — 08 §Runs' `{ok, note?}` — and is omitted when there is
    nothing to say rather than sent as an empty string.
    """

    ok: bool = Field(
        default=True, description="Always true; a failure is an error body."
    )
    note: str | None = Field(
        default=None,
        description="What was unusual about the success, when anything was.",
    )


class Created(BaseModel):
    """The 201 body of ``POST /api/workflows/{name}/runs`` (08 §Workflows)."""

    run_id: str = Field(description="The id of the run that was queued.")


class TaskRef(BaseModel):
    """The id of a task an operator verb queued.

    The answer to ``rerun``, ``retry`` and ``move``: each of the three
    ends with a **new** attempt row, and this is its id (08 §Runs,
    §Tasks).
    """

    task_id: int = Field(description="The id of the task that was enqueued.")


class LogRef(BaseModel):
    """The id of a work-log entry that was appended (08 §Runs)."""

    log_id: int = Field(description="The id of the entry that was written.")
