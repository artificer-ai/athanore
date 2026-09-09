"""feature_build — the starter pipeline of DESIGN.md, expressed as code.

The eight stages of the MVP's pipeline, written against the v1 API:

    prompt → product → architecture → engineering → review ⇄ qa → gate → git
                 │                        ↑            │        │     │
                 └─ fan-out ─┐            └────────────┴────────┴─────┘
                             └──────► (the same tail, per branch)

**State flows through the run's work log, not through payloads.** Every
agent reads the whole log — every earlier stage, every earlier attempt —
appends its deliverable to it, and the node returns a bare edge reference.
The one payload in the graph is the product stage's fan-out, because that
is the one place where the branches have to be told apart: one branch per
deliverable, each running the rest of the pipeline for itself.

**Three stages are decisions, and two of those are models.** ``review``
and ``qa`` route on a :class:`~feature_build.models.ReviewDecision` an
agent submitted, so the verdict is an ``output_model`` rather than a
sentence somebody has to parse. ``gate`` routes on an exit code and has
no agent at all: the model that wrote the code never gets to say whether
its own tests passed.

**Retries and timeouts are node options** (04 §Node options), which is
the whole reason they exist: a body that counted its own attempts would
be re-implementing rule 3 inside rule 1. ``git`` is the one node with
``retries=0`` — a commit that half happened is not improved by doing it
again.

``scenarios/`` is what makes this runnable with no model in the loop
(13 §Running examples on the fake): one ``feature_build.<node>.json`` per
agent stage, each logging a plausible deliverable and submitting a value
its stage's ``output_model`` accepts, selected by the fake out of
``ATHANORE_FAKE_SCENARIOS`` while ``ATHANORE_AGENT_COMMAND`` points every
seat at it. ``gate`` has no file and cannot have one — it is the node
with no agent — so a scripted run reaches ``git`` exactly where
:data:`GATE_COMMAND` is green in the directory the server was started in,
and loops back to ``engineering`` where it is not. That is the pipeline
working, not the fixture failing.

Submit work with the CLI::

    athanore submit feature_build "Build feature xyz" "As a user I want ..."

and serve it with ``athanore serve`` (it is an entry point of the
``athanore-examples`` distribution) or with ``python -m examples``.
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

from pydantic import BaseModel

from athanore import AgentResult, NonRetryable, Workflow, current_task

from .architect import ArchitectAgent
from .base import MODEL, FeatureBuildAgent
from .code_reviewer import CodeReviewerAgent
from .git_engineer import GitEngineerAgent
from .models import Deliverable, ProductSpec, ReviewDecision
from .product_manager import ProductManagerAgent
from .prompt_engineer import PromptEngineerAgent
from .qa_engineer import QAEngineerAgent
from .software_engineer import SoftwareEngineerAgent

__all__ = [
    "GATE_COMMAND",
    "GATE_TAIL",
    "MODEL",
    "ArchitectAgent",
    "CodeReviewerAgent",
    "Deliverable",
    "FeatureBuildAgent",
    "GitEngineerAgent",
    "ProductManagerAgent",
    "ProductSpec",
    "PromptEngineerAgent",
    "QAEngineerAgent",
    "ReviewDecision",
    "SoftwareEngineerAgent",
    "wf",
]

M = TypeVar("M", bound=BaseModel)

#: What the deterministic gate runs, in the server's working directory —
#: which is the repository the agents have been working in. It is a
#: constant rather than a setting because a pipeline whose gate is
#: configurable is a pipeline whose gate can be configured away.
GATE_COMMAND = ("uv", "run", "pytest", "-q")

#: How much of the gate's output reaches the work log. The tail is where
#: pytest puts the summary and the failures; the head is collection.
GATE_TAIL = 1500


def _completed(result: AgentResult) -> AgentResult:
    """``result``, or a dead letter (04 §Failure classes).

    A refusal, a cancellation and a truncated final turn come back as a
    *failed result* rather than an exception, so that the body decides
    what they mean (05 §AgentResult). Here they mean the same thing at
    every stage: the agent did not do the work, and asking the same model
    the same question again is not a plan. :class:`NonRetryable` is what
    says so — it dead-letters the task and leaves the run for an operator,
    with the reason on the row.
    """

    if result.ok:
        return result
    raise NonRetryable(
        result.error or f"the agent stopped: {result.stop_reason or 'no reason given'}"
    )


def _submitted(result: AgentResult, model: type[M]) -> M:
    """The validated submission of a completed run, typed.

    ``AgentResult.output`` is ``Any`` — the façade validated it against
    whatever the agent class declared — and the body knows which model
    that was. Narrowing it here is what lets the two nodes that route on
    a verdict read ``.verdict`` under a type checker, and it turns "the
    agent submitted nothing" into the same dead letter a refusal earns
    rather than an ``AttributeError`` three lines later.
    """

    output = _completed(result).output
    if isinstance(output, model):
        return output
    raise NonRetryable(
        f"expected a {model.__name__} submission, got "
        f"{type(output).__name__}: {output!r}"
    )


def _assignment(deliverable: Any) -> str:
    """The one deliverable this branch is for, as the assignment section.

    Payloads are coerced with ``jsonable()`` (04 §Routing interpretation),
    so the :class:`~feature_build.models.Deliverable` the product stage
    submitted arrives here as a dict. An operator who moved a task onto
    this node by hand may have sent nothing at all, and that is not an
    error — the spec and the split are in the work log, which is the
    agent's real input, so an empty assignment simply adds no section
    (19 §Assembly).
    """

    if deliverable is None:
        return ""
    if isinstance(deliverable, dict):
        parts = [str(deliverable.get(key, "")) for key in ("title", "description")]
        described = ". ".join(part for part in parts if part)
    else:
        described = str(deliverable)
    return f"Deliverable for this branch: {described}" if described else ""


wf = Workflow("feature_build")


@wf.node(start=True, retries=1, timeout=600)
async def prompt(product):
    """Reword the raw brief into a well-formed task description."""

    _completed(await PromptEngineerAgent().run())
    return product


@wf.node(retries=1, timeout=1800)
async def product(architecture):
    """Write the spec, and split it into one deliverable per branch."""

    spec = _submitted(await ProductManagerAgent().run(), ProductSpec)
    # The one payload in the graph: a called edge ref carries the value
    # that tells the branches apart. `deliverables` is non-empty by the
    # model, so this is never the empty fan-out that ends a run.
    return [architecture(one) for one in spec.deliverables]


@wf.node(retries=1, timeout=1800)
async def architecture(engineering, *, deliverable):
    """Turn this branch's deliverable into an implementation plan."""

    _completed(await ArchitectAgent().run(_assignment(deliverable)))
    return engineering


@wf.node(retries=1, timeout=10800)
async def engineering(review):
    """Implement the plan, or fix what review, QA or the gate found.

    On a loop-back the agent is handed nothing new: the findings are in
    the work log it reads first, which is the same log it appended its
    own last attempt to.
    """

    _completed(await SoftwareEngineerAgent().run())
    return review


@wf.node(retries=1, timeout=3600)
async def review(engineering, qa):
    """Review the change; approve it to QA or send it back."""

    decision = _submitted(await CodeReviewerAgent().run(), ReviewDecision)
    return qa if decision.verdict == "approve" else engineering


@wf.node(retries=1, timeout=3600)
async def qa(engineering, gate):
    """Exercise the feature; approve it to the gate or send it back."""

    decision = _submitted(await QAEngineerAgent().run(), ReviewDecision)
    return gate if decision.verdict == "approve" else engineering


@wf.node(retries=1, timeout=3600)
async def gate(engineering, git):
    """Run the repository's test suite and route on the exit code.

    No agent: green goes to git, red goes back to engineering with the
    output. This is the one verdict in the pipeline that no model gets a
    say in, which is the point of it.
    """

    try:
        process = await asyncio.create_subprocess_exec(
            *GATE_COMMAND,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        # The command is not on this machine. Retrying spawns the same
        # missing executable, so the run stops here and says which one.
        raise NonRetryable(
            f"the gate command {' '.join(GATE_COMMAND)} could not be run: {exc}"
        ) from exc
    stdout, _ = await process.communicate()
    passed = process.returncode == 0
    tail = stdout.decode(errors="replace").rstrip()[-GATE_TAIL:]

    # A node with no agent still writes to the shared work log: on a
    # loop-back this is the whole of what the engineer is told.
    ctx = current_task()
    await ctx.services.log.append(
        f"test gate: {'PASS' if passed else 'FAIL'}\n{tail}",
        author="engine",
        kind="note" if passed else "failure",
    )
    return git if passed else engineering


@wf.node(retries=0, timeout=900)
async def git():
    """Commit the verified change. Terminal: no edges, so the branch ends.

    ``retries=0`` because a commit is not idempotent: an attempt that
    failed after writing one is not repaired by writing it again.
    """

    return _completed(await GitEngineerAgent().run()).text
