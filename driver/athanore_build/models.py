"""Structured submissions the sandbox agents make (v0 `output_model`)."""

from pydantic import BaseModel, Field


class TaskReport(BaseModel):
    """What the implementer submits when it believes a task is done."""

    task_id: str = Field(description="The task id, e.g. T012")
    commit: str = Field(description="The commit sha created for this task")
    summary: str = Field(description="What was built, in two or three sentences")
    files: list[str] = Field(default_factory=list, description="Files touched")
    tests_added: list[str] = Field(default_factory=list, description="Test files added")
    gate_ran: bool = Field(description="Whether ./scripts/test.sh was run to green")
    open_points: str = Field(default="", description="Anything left undecided")


class ReviewVerdict(BaseModel):
    """The reviewer's verdict on the implementer's commit."""

    ok: bool = Field(description="True only if the commit does exactly the task")
    notes: str = Field(description="What is wrong, or why it passes")
