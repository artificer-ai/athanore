"""The structured submissions `feature_build` routes on.

Rule 2 is "the return value is the routing", and two of this pipeline's
stages route on something an agent said. That is what an ``output_model``
is for: the model becomes the submission schema in the agent's prompt (19
§Submission instructions) or the input schema of its ``submit_result``
tool (05 §Tooling tiers), the agent API validates against it, and a
submission that does not fit earns a repair turn rather than a body that
has to guess what it was handed.

So the constraints here are load-bearing rather than decoration.
:attr:`ProductSpec.deliverables` is non-empty because the node fans out
over it: an empty list would end the run at the product stage with
nothing built and nothing said, and as a ``min_length`` it is instead a
422 the agent is asked to fix inside the same session.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["Deliverable", "ProductSpec", "ReviewDecision"]


class Deliverable(BaseModel):
    """One self-contained piece of work: a branch of the pipeline.

    Every deliverable the product stage lists becomes its own branch
    (architecture → engineering → review → qa → gate → git), so each has
    to stand on its own — which is what the two fields are for and why
    both are required.
    """

    title: str
    description: str


class ProductSpec(BaseModel):
    """What the product stage submits: the spec it wrote, and the split."""

    spec_path: str
    #: At least one. The node fans out over this list, and a fan-out of
    #: nothing is a run that completes having built nothing (04 §Routing
    #: edge cases: `return []` is terminal).
    deliverables: list[Deliverable] = Field(min_length=1)


class ReviewDecision(BaseModel):
    """A verdict and the findings behind it: what review and QA submit.

    ``feedback`` is the loop-back's payload in everything but name — the
    engineer reads it out of the work log — so it is optional only
    because an approval has nothing to say.
    """

    verdict: Literal["approve", "changes_requested"]
    feedback: str = ""
