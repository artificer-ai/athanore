"""What a client sends: one model per operator POST or PATCH (08 §Endpoints).

Bodies are pydantic models and a body that misfits is the 422 of 08
§Conventions, so what is stated here is what the API refuses before any
engine operation is attempted. Two rules run through all of them:

- **A text field a row cannot be without is stripped and required
  non-empty.** A run titled `"   "` is unfindable in every list that
  shows a title, and a work-log entry of whitespace says nothing; both
  are a 422 rather than a refusal from deeper down, because the body is
  where the caller can see what was wrong.
- **A choice with a fixed set of values is a ``Literal``**, so the
  generated TypeScript is a union and a wrong value never reaches the
  engine (`direction`, `status`).

Nothing here decides anything else. The preconditions — a run that is not
paused, a node that is a join target, a request already answered — belong
to the engine and the request service, which is where every router sends
them.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, StringConstraints, model_validator

from athanore.engine.ops import SettableStatus

__all__ = [
    "Answer",
    "EditRun",
    "LogText",
    "Move",
    "NewRun",
    "Position",
    "RegisterWorkflow",
    "ReloadWorkflow",
    "Rerun",
    "SetStatus",
]

#: A string that is stripped and may not be empty afterwards. What a
#: title, a node name and a log entry all are.
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class NewRun(BaseModel):
    """Submit a run of a workflow (`POST /api/workflows/{name}/runs`).

    The two fields become the start task's payload, which is why editing
    either afterwards does not rewrite it (04 §Submit a run).
    """

    title: Text = Field(description="The operator's title for the run.")
    description: str = Field(
        default="", description="Longer context for the run; the workflow's input."
    )


class EditRun(BaseModel):
    """Change a run's title, its description, or both (`PATCH /api/runs/{id}`).

    Both fields are optional and a field that is absent is left alone —
    which is why they are optional rather than defaulted: an edit that
    sent no description must not blank one. An edit that names neither is
    accepted and changes nothing, which is what ``Ops.edit`` does with it:
    a patch is not the place to refuse a caller for being redundant.
    """

    title: Text | None = Field(default=None, description="The new title, if changing.")
    description: str | None = Field(
        default=None, description="The new description, if changing."
    )


class Position(BaseModel):
    """Move a run in the dispatch list (`POST /api/runs/{id}/position`, D57).

    Exactly one of the two. ``direction`` swaps with the neighbour above
    (``-1``) or below (``+1``) and is a no-op at the ends — still a 200,
    reporting the position the run already had. ``index`` is the
    **zero-based** list index to move to, clamped to the list; New Run's
    "top" is `{"index": 0}` and "bottom" is the default, which needs no
    call at all.
    """

    direction: Literal[-1, 1] | None = Field(
        default=None, description="Swap with the neighbour above (-1) or below (1)."
    )
    index: int | None = Field(
        default=None, description="The zero-based list index to move to, clamped."
    )

    @model_validator(mode="after")
    def _exactly_one(self) -> Position:
        if (self.direction is None) == (self.index is None):
            raise ValueError("give exactly one of `direction` and `index`")
        return self


class LogText(BaseModel):
    """Append an entry to a run's work log (`POST /api/runs/{id}/log`)."""

    text: Text = Field(description="The entry, written verbatim and never truncated.")


class Rerun(BaseModel):
    """Run a node again (`POST /api/runs/{id}/rerun`).

    The payload and branch it last had are re-used; a rerun of a join
    replays the arrivals it fired on (04 §Operator operations).
    """

    node: Text = Field(description="The node to run again.")


class Move(BaseModel):
    """Move a task's work to another node (`POST /api/tasks/{id}/move`)."""

    node: Text = Field(description="The node to enqueue the work at.")


class SetStatus(BaseModel):
    """Write one of the three statuses an operator may set (08 §Tasks).

    The other four are the engine's own record of what happened and are
    not an operator's to declare.
    """

    status: SettableStatus = Field(
        description="`ready` re-dispatches the task, `cancelled` stops it, "
        "`dead_letter` files it as failed for good."
    )


class Answer(BaseModel):
    """Answer a request (`POST /api/requests/{id}/answer`, 06 §The model).

    ``option_id`` for an ``options`` request and ``value`` for a ``text``
    or ``form`` one. Both are optional here because ``value`` may
    legitimately be any JSON — including ``null``, which is why "which one
    was given" cannot be decided by looking at the values alone: the
    request's own ``mode`` decides, and the request service refuses the
    mismatch with the error code 06 §Errors names for it.
    """

    option_id: str | None = Field(
        default=None, description="The chosen option, for an `options` request."
    )
    value: Any = Field(
        default=None, description="The answer, for a `text` or `form` request."
    )


class RegisterWorkflow(BaseModel):
    """Register a workflow on the running server (`POST /api/workflows`, 22 §Wire).

    ``target`` names the workflow as `athanore serve` would: `module:attr`
    or `path/to/file.py:attr`. The name it registers under is the loaded
    ``Workflow``'s own. ``pool`` must already exist on the engine — a
    live registration never creates one — and ``persist`` writes the
    `[workflows.<name>]` row of `athanore.toml` before anything is
    mutated, so a target that does not load is never written down.
    """

    target: Text = Field(
        description="The workflow to load: `module:attr` or `path/to/file.py:attr`."
    )
    pool: str | None = Field(
        default=None,
        description="The pool to bind the workflow to; the default pool when omitted.",
    )
    persist: bool = Field(
        default=False,
        description="Write the registration as a `[workflows.<name>]` row of "
        "`athanore.toml`; the response then carries `X-Athanore-Persisted`.",
    )


class ReloadWorkflow(BaseModel):
    """Replace a registered workflow (`PUT /api/workflows/{name}`, 22 §Wire).

    ``target`` omitted re-resolves the registration's recorded target —
    what `athanore serve` or an earlier registration loaded it from — and
    is refused when there is none. A target that now defines a differently
    named workflow is refused too: that is a new workflow, and `POST` is
    how it arrives. ``pool`` omitted keeps the binding the name has.
    """

    target: Text | None = Field(
        default=None,
        description="The workflow to load; the registration's recorded target "
        "when omitted.",
    )
    pool: str | None = Field(
        default=None,
        description="The pool to move the workflow to; the current binding when "
        "omitted. Refused while any attempt of the workflow is in flight.",
    )
    persist: bool = Field(
        default=False,
        description="Rewrite the `[workflows.<name>]` row of `athanore.toml`; the "
        "response then carries `X-Athanore-Persisted`.",
    )
