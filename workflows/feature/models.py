"""What the three agents of `feature` submit.

Each is the `output_model` of the node that routes on it, so a verdict is
a validated object rather than a sentence somebody has to parse — a stage
that answered in prose would put the routing decision back in the hands
of whoever read it (rule 2).

None of them carries a commit sha, a branch name or a pass/fail on the
test suite. Those are facts about the repository, and the nodes read them
from git and from the gate's exit code: an agent that reported its own
work as green would be the one thing this pipeline exists to prevent.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["Brief", "PlanDoc", "QAVerdict", "ReviewVerdict", "TaskReport"]


class Brief(BaseModel):
    """The operator's request, rewritten into one the next stage can use.

    Deliberately thin. This is the cheapest seat in the pipeline and it
    is not the one that decides anything: it sharpens a sentence into a
    statement of the outcome, and the architecture is the planner's.
    There is no `title` here on purpose — the title is the branch, the
    merge subject and the glob that finds the plan, so it is the
    operator's and no model gets to change it.
    """

    description: str = Field(
        description=(
            "The request rewritten: what must be true when this is done, "
            "stated as the outcome rather than as an implementation, with "
            "the documents and modules it touches named"
        )
    )
    out_of_scope: list[str] = Field(
        default_factory=list,
        description=(
            "What a reader might reasonably assume is included and is "
            "not — the line that stops the next stage building more than "
            "was asked for"
        ),
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description="What the request does not settle, each one a question",
    )


class PlanDoc(BaseModel):
    """The plan the architect filed for this one task.

    `plan` is read back off the branch rather than trusted: the node
    checks that the file exists and that it is the one
    `sandbox.plan_docs(title)` resolves, because a plan the implementer
    cannot find is a plan that was never written.
    """

    plan: str = Field(
        description=(
            "The plan file written for this task, checkout-relative: "
            "`docs/plans/<run title>-<slug>.md`"
        )
    )
    summary: str = Field(description="The approach, in two or three sentences")
    files: list[str] = Field(
        default_factory=list,
        description="The files the change is expected to touch",
    )


class TaskReport(BaseModel):
    """The implementer's account of what it did."""

    headline: str = Field(
        description=(
            "One line, imperative mood, no trailing period — the subject "
            "line of the merge commit this becomes"
        )
    )
    summary: str = Field(description="What was built, in two or three sentences")
    files: list[str] = Field(default_factory=list, description="Files touched")
    tests_added: list[str] = Field(default_factory=list, description="Test files added")
    how_to_exercise: str = Field(
        default="",
        description=(
            "How a reviewer can see this working: the command to run, the "
            "endpoint to call, the page to open"
        ),
    )
    open_points: str = Field(default="", description="Anything left undecided")


class ReviewVerdict(BaseModel):
    """The reviewer's verdict on the branch diff."""

    ok: bool = Field(
        description=(
            "True to send the branch to QA, false to send it back to the "
            "implementer with `blocking`"
        )
    )
    blocking: list[str] = Field(
        default_factory=list,
        description=(
            "What must change before this can merge, each one specific "
            "enough to act on without asking a question"
        ),
    )
    notes: str = Field(description="The reasoning behind the verdict")


class QAVerdict(BaseModel):
    """QA's verdict, from exercising the running feature."""

    ok: bool = Field(description="True only if the feature was actually made to work")
    checks: list[str] = Field(
        default_factory=list,
        description=(
            "What was exercised and what happened, one per line, e.g. "
            "'GET /api/health -> 200 {\"ok\": true}'"
        ),
    )
    evidence: str = Field(default="", description="The commands run and their output")
    notes: str = Field(description="What failed, or why it passes")
