"""The structured submissions `gamedev` routes on, and its plugin's form.

Four of these are what an agent submits and the graph reads; the fifth,
:class:`Override`, is what an *operator* submits — the input model of the
``override`` action, which 09 §Declarations makes the form the SPA
renders. They live together because they are the same kind of thing: a
shape this workflow refuses to be handed anything else in.

The constraints are load-bearing, not decoration:

- :attr:`GameSpec.deliverables` is non-empty because the director node
  fans out over it, and ``return []`` is terminal (04 §Routing edge
  cases): an empty list would end a run having built nothing.
- :attr:`Deliverable.file_path` is ``output/<slug>.html`` by pattern
  because "one game = one HTML file under ``output/``" is the constraint
  every prompt in this pipeline states. As a pattern it is a 422 the
  director repairs inside its own session (19 §Repair turn); as prose it
  is a path the engineer writes to and nobody notices.
- :attr:`ArchitecturePlan.steps` is non-empty because the engineering
  node executes the list serially, and a plan with no steps is a branch
  that hands an unbuilt file to review.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "FILE_PATH_PATTERN",
    "ArchitecturePlan",
    "BuildStep",
    "Deliverable",
    "GameSpec",
    "Override",
    "ReviewDecision",
]

#: ``output/<slug>.html``, lowercase and hyphenated. The one place this
#: pipeline's "one game, one file" rule is machine-checked.
FILE_PATH_PATTERN = r"^output/[a-z0-9]+(?:-[a-z0-9]+)*\.html$"


class Deliverable(BaseModel):
    """One finished game: a branch of the pipeline, and a file on disk."""

    title: str = Field(min_length=1, description="The game's name.")
    description: str = Field(
        min_length=1,
        description="This branch's charter: concept, mechanics, acceptance.",
    )
    file_path: str = Field(
        pattern=FILE_PATH_PATTERN,
        description="Where the finished game lives: output/<slug>.html.",
    )


class GameSpec(BaseModel):
    """What the director submits: the split, and one line over it."""

    summary: str = Field(min_length=1)
    #: At least one. The node fans out over this list.
    deliverables: list[Deliverable] = Field(min_length=1)


class BuildStep(BaseModel):
    """One serial engineering step within a branch's single-file build."""

    name: str = Field(min_length=1, description='Short id: "scaffold", "physics".')
    charter: str = Field(min_length=1, description="Exactly what this step builds.")
    done_when: str = Field(
        min_length=1,
        description="A completion criterion checkable from disk.",
    )


class ArchitecturePlan(BaseModel):
    """The architect's ordered build-step list.

    Executed serially by the engineering node — one agent session per
    step, each appending to the same file. ``steps[0]`` scaffolds a valid
    file; every later step keeps it parsing.
    """

    summary: str = Field(min_length=1)
    steps: list[BuildStep] = Field(min_length=1)


class ReviewDecision(BaseModel):
    """A verdict and the findings behind it: what review and QA submit."""

    verdict: Literal["approve", "changes_requested"]
    feedback: str = ""


# The ``override`` action's input, and therefore the form the SPA renders
# (09 §Declarations). Its docstring and its field descriptions are shown
# to the operator above the form, so both are written as prose for
# somebody reading them in a browser: reStructuredText markup that reads
# as emphasis in a source file reads as stray punctuation there.
class Override(BaseModel):
    """Rename the game this run is building.

    The new name replaces the one the director chose. It goes to the work
    log, which every stage of this pipeline reads, so the engineer picks
    it up on its next pass and the title screen and the HUD follow. The
    file on disk does not move.
    """

    word: str = Field(
        min_length=1,
        description="The name the game must go by from here on.",
    )
    reason: str = Field(
        default="",
        description="Why, for the log and for the engineer who reads it.",
    )
