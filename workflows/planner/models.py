"""What the two agents of `planner` submit, and what the operator answers.

Each is the `output_model` of the node that routes on it, so a verdict is
a validated object rather than a sentence somebody has to parse — a stage
that answered in prose would put the routing decision back in the hands
of whoever read it (rule 2).

None of them carries a commit sha, a file listing taken from the agent's
word, or a claim that the documents were written. Those are facts about
the repository, and :mod:`workflows.planner.checks` reads them from git:
an architect that reported its own plan as filed would be the one thing
this pipeline exists to prevent, exactly as in `feature`.

:class:`PlannedTask` is the seam between the two workflows. Its ``id`` is
the title of the `feature` run the plan produces, which makes it the
branch name, the prefix of the merge commit subject, and the glob
`workflows.checkout.plan_docs` looks the plan file up by. Getting it
wrong does not fail loudly later — it hands an implementer somebody
else's plan — so `checks` verifies every part of it against the tree
before a single run is queued.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["Brief", "Decision", "PlanProposal", "PlannedTask"]


class Brief(BaseModel):
    """The enhancer's reading of what the operator asked for."""

    goal: str = Field(
        description=(
            "What the operator actually wants, in a paragraph, stated as "
            "the outcome rather than as an implementation"
        )
    )
    context: str = Field(
        description=(
            "What in this repository it touches: the documents in `docs/v1/` "
            "that specify it and the modules that would change, by name"
        )
    )
    requirements: list[str] = Field(
        default_factory=list,
        description=(
            "The behaviour that must exist when this is done, one per "
            "entry, each one specific enough to be tested"
        ),
    )
    out_of_scope: list[str] = Field(
        default_factory=list,
        description="What a reader might reasonably assume is included and is not",
    )
    open_questions: list[str] = Field(
        default_factory=list,
        description=(
            "What the specs do not settle and the boring choice does not "
            "answer — each one a question, not a topic"
        ),
    )

    def as_markdown(self) -> str:
        """The brief as the architect and the work log read it."""

        def bullets(heading: str, items: list[str]) -> str:
            if not items:
                return ""
            body = "\n".join(f"- {item}" for item in items)
            return f"\n\n## {heading}\n{body}"

        return (
            f"## Goal\n{self.goal}\n\n## Context\n{self.context}"
            + bullets("Requirements", self.requirements)
            + bullets("Out of scope", self.out_of_scope)
            + bullets("Open questions", self.open_questions)
        )


class PlannedTask(BaseModel):
    """One implementation task, and the `feature` run it becomes."""

    id: str = Field(
        description=(
            "The task id, `T` and digits with an optional lowercase "
            "suffix — `T080`, `T081a`. It becomes the title of the "
            "`feature` run, so it must not be an id any earlier task used"
        )
    )
    title: str = Field(description="What the task is called, in a few words")
    plan: str = Field(
        description=(
            "The plan file written for this task, checkout-relative and "
            "under `docs/plans/`, named `docs/plans/<id>-<slug>.md`"
        )
    )
    description: str = Field(
        description=(
            "The brief the implementer is given: what to build, what the "
            "exit condition is, and which spec sections to read"
        )
    )


class PlanProposal(BaseModel):
    """The architect's plan, as filed on the branch."""

    document: str = Field(
        description=(
            "The design document written for this feature, "
            "checkout-relative and under `docs/v1/`"
        )
    )
    summary: str = Field(description="The design, in two or three sentences")
    tasks: list[PlannedTask] = Field(
        description=(
            "The implementation tasks, in the order they must be built. "
            "Serial: each one lands on `main` before the next begins"
        )
    )
    decisions: list[str] = Field(
        default_factory=list,
        description="Choices the documents did not make, as added to `15-decisions.md`",
    )
    open_points: str = Field(
        default="",
        description=(
            "What the operator has to rule on, or empty. This is what "
            "they are shown at the approval gate"
        ),
    )


class Decision(BaseModel):
    """The operator's ruling on a proposal.

    A form rather than a row of buttons because the three answers and the
    reason for them are one thought: sending an architect back with no
    instruction costs a whole agent turn to learn nothing.
    """

    decision: Literal["approve", "revise", "abandon"] = Field(
        description=(
            "`approve` to merge the plan and queue the work, `revise` to "
            "send it back with your feedback, `abandon` to stop and leave "
            "the branch unmerged"
        )
    )
    feedback: str = Field(
        default="",
        description="What to change. Required to revise; ignored otherwise",
    )
