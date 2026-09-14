"""The one output model the shared steps read.

The verdict models — the brief, the plan, the review, the QA pass — are
`feature`'s and stay in :mod:`workflows.feature.models`. The implementer's
report is here because :func:`workflows.shared.steps.implement` reads its
``headline`` for the merge subject whichever workflow's implementer
wrote it.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["TaskReport"]


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
