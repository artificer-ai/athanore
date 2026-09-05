"""Structured submissions the sandbox agents make (v0 `output_model`).

None of these carry a commit sha or a pass/fail on the test suite: the
workflow reads those from git and from the gate's exit code. An agent
reports what it *did*; it never reports whether it succeeded.
"""

from pydantic import BaseModel, Field


class TaskReport(BaseModel):
    """What the implementer submits when it believes the work is done."""

    headline: str = Field(
        description="One imperative line for the merge commit, e.g. "
        "'add the package skeleton and the graph builder'"
    )
    summary: str = Field(description="What was built, in two or three sentences")
    files: list[str] = Field(default_factory=list, description="Files touched")
    tests_added: list[str] = Field(default_factory=list, description="Test files added")
    how_to_exercise: str = Field(
        default="",
        description="How a reviewer can see this working: the command to run, "
        "the endpoint to call, the CLI invocation, the page to open. Say so "
        "plainly if the change has no runnable surface yet.",
    )
    open_points: str = Field(default="", description="Anything left undecided")


class ReviewVerdict(BaseModel):
    """The reviewer's verdict on the branch's diff."""

    ok: bool = Field(
        description="True only if the diff does exactly the task, at the "
        "quality bar, with nothing stubbed and nothing extra"
    )
    blocking: list[str] = Field(
        default_factory=list,
        description="Each defect that must be fixed, one per entry, each "
        "naming the file and what is wrong",
    )
    notes: str = Field(description="The reasoning behind the verdict")


class QAVerdict(BaseModel):
    """The QA agent's verdict from exercising the feature for real."""

    ok: bool = Field(
        description="True only if what was checked actually worked. A change "
        "with no runnable surface yet is ok=true with the checks that were "
        "possible listed"
    )
    checks: list[str] = Field(
        default_factory=list,
        description="Each check actually performed, with its result, e.g. "
        "'GET /api/health -> 200 {\"ok\": true}'",
    )
    evidence: str = Field(
        default="",
        description="Commands run and the output that proves the result",
    )
    notes: str = Field(description="What failed, or why it passes")
