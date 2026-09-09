"""gamedev — a pipeline that builds finished single-file HTML games.

One game per branch; the director fans out one branch per game:

    prompt → design → director → architecture → engineering → review
                          │                          ▲          │
                          └─ fan-out ─┐              │          ▼
                                      │              │      human_qa
                                      ▼              │          │
                          (the same tail, per branch)│          ▼
                                                     └──────── qa ──▶ publish

**Hard constraints, in every stage's prompt.** One game = one HTML file
under ``output/``; no local assets (graphics procedural, audio
synthesized); external dependencies only over a CDN. There is **no
deterministic gate**: there are no unit tests for a game, so the browser
is the test — QA loads the file in a real Chrome through pi's
`browser-tools` skill and plays it, and a person plays it before that.

**Engineering is not one session.** A finished game does not come out of
a single turn, so the architect submits an ordered build-step list —
scaffold first — and the engineering node runs one focused agent session
per step, each appending to the same file. Review and QA drop the plan
when they route back, and the node reads that as "one targeted fix"
rather than "build it again".

**The one human in the loop is a playtest.** ``human_qa`` asks the
operator to open the file and try it, and threads the reply into QA's
assignment, where it is part of the verdict rather than advice. That is
`human_input` (04 §Waiting): the attempt gives its pool slot back while
it waits, so a game waiting to be played does not hold the one worker
this workflow's pool has.

**It is also the plugin showcase.** 09 §Declarations' example is this
workflow, and :mod:`gamedev.plugin` is it built for real: the ``/words``
route, the ``override`` action, and the ``Words`` table pane. A game's
name is the subject of all three.

``scenarios/`` is what makes this runnable with no model in the loop (13
§Running examples on the fake): one ``gamedev.<node>.json`` per agent
stage. ``human_qa`` and ``publish`` have none and cannot have one — they
run no agent — so a scripted run stops at the playtest question until it
is answered, which is the pipeline working rather than the fixture
failing.

Submit work with the CLI::

    athanore submit gamedev "Neon snake" "A fast, juicy snake with..."

and serve it with ``athanore serve`` (it is an entry point of the
``athanore-examples`` distribution) or with ``python -m examples``.
"""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from athanore import (
    AgentError,
    AgentResult,
    NonRetryable,
    Workflow,
    current_task,
    human_input,
)

from .architect import GameArchitectAgent
from .base import MODEL, GamedevAgent
from .engineer import GameEngineerAgent
from .game_designer import GameDesignerAgent
from .game_director import GameDirectorAgent
from .models import (
    FILE_PATH_PATTERN,
    ArchitecturePlan,
    BuildStep,
    Deliverable,
    GameSpec,
    Override,
    ReviewDecision,
)
from .plugin import WORD, WORD_COLUMNS, declare, overridden, word_entry, word_row
from .prompt_writer import PromptWriterAgent
from .qa_engineer import QAEngineerAgent
from .reviewer import GameReviewerAgent

__all__ = [
    "FILE_PATH_PATTERN",
    "MODEL",
    "PLAYTEST_QUESTION",
    "WORD",
    "WORD_COLUMNS",
    "ArchitecturePlan",
    "BuildStep",
    "Deliverable",
    "GameArchitectAgent",
    "GameDesignerAgent",
    "GameDirectorAgent",
    "GameEngineerAgent",
    "GameReviewerAgent",
    "GameSpec",
    "GamedevAgent",
    "Override",
    "PromptWriterAgent",
    "QAEngineerAgent",
    "ReviewDecision",
    "declare",
    "overridden",
    "wf",
    "word_entry",
    "word_row",
]

M = TypeVar("M", bound=BaseModel)

#: What the operator is asked to do at the playtest, with the branch's
#: file substituted in. A constant because the Playwright suite and the
#: CLI both have to recognise the question they are answering.
PLAYTEST_QUESTION = (
    "Human playtest: open {file_path} in a browser and try the game.\n"
    "Reply 'pass' if it is good to ship, or describe what is wrong / "
    "what you want changed."
)


def _completed(result: AgentResult) -> AgentResult:
    """``result``, or a dead letter (04 §Failure classes).

    A refusal, a cancellation and a truncated final turn come back as a
    *failed result* rather than an exception, so the body decides what
    they mean (05 §AgentResult). At every stage but engineering they
    mean the same thing: the agent did not do the work, and asking the
    same model the same question again is not a plan.
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


def _field(value: Any, key: str) -> str:
    """One field of a deliverable, whatever shape the payload arrived in.

    Payloads are coerced with ``jsonable()`` (04 §Routing interpretation),
    so the :class:`~gamedev.models.Deliverable` the director submitted
    reaches the tail as a dict. An operator who moved a task onto one of
    these nodes by hand may have sent something else, or nothing at all,
    and that is not an error: the design and the split are in the work
    log, which is the agent's real input.
    """

    if isinstance(value, dict):
        return str(value.get(key, ""))
    return str(value) if value is not None and key == "title" else ""


def _assignment(deliverable: Any) -> str:
    """The one game this branch is for, as the assignment section (19)."""

    title = _field(deliverable, "title")
    file_path = _field(deliverable, "file_path")
    description = _field(deliverable, "description")
    lines = [
        line
        for line in (f"Target file: {file_path}." if file_path else "", description)
        if line
    ]
    if not title and not lines:
        return ""
    head = "Deliverable for this branch"
    return "\n".join([f"{head}: {title}." if title else f"{head}.", *lines])


def _step_assignment(deliverable: Any, step: Any, index: int, total: int) -> str:
    """Per-step kickoff: the branch's game plus this step's charter."""

    name = _field(step, "name")
    role = "SCAFFOLD step" if index == 1 else f"Build step {index}/{total}"
    final = " This is the FINAL build step." if index == total else ""
    return (
        f"{role}: {name} ({index}/{total}).{final}\n"
        f"Charter: {_field(step, 'charter')}\n"
        f"Done when: {_field(step, 'done_when')}\n\n"
        f"{_assignment(deliverable)}"
    )


wf = Workflow("gamedev")


@wf.node(start=True, retries=1, timeout=600)
async def prompt(design):
    """Reword the raw request into a well-formed game brief."""

    _completed(await PromptWriterAgent().run())
    return design


@wf.node(retries=1, timeout=1800)
async def design(director):
    """Turn the brief into a complete, buildable game design."""

    _completed(await GameDesignerAgent().run())
    return director


@wf.node(retries=1, timeout=1800)
async def director(architecture):
    """Split the design into games, and fan out one branch per game."""

    spec = _submitted(await GameDirectorAgent().run(), GameSpec)
    # The names this run's games go by, as data rather than as prose: the
    # `Words` pane reads these rows, and the engineer reads the same
    # lines as part of the log. Written by the node so that a row does
    # not depend on how the model happened to phrase its own log entry.
    log = current_task().services.log
    for one in spec.deliverables:
        await log.append(
            word_entry(one.title, file_path=one.file_path),
            author="engine",
            kind="note",
        )
    # The one payload in the graph: a called edge ref carries the value
    # that tells the branches apart. `deliverables` is non-empty by the
    # model, so this is never the empty fan-out that ends a run.
    return [architecture(one) for one in spec.deliverables]


@wf.node(retries=1, timeout=1800)
async def architecture(engineering, *, deliverable):
    """Plan the single-file build, as an ordered list of build steps."""

    plan = _submitted(
        await GameArchitectAgent().run(_assignment(deliverable)), ArchitecturePlan
    )
    # The tail threads a composite: the game this branch owns, and the
    # plan engineering executes. Review and QA drop the plan when they
    # route back, which is how the node tells a build from a fix.
    return engineering({"deliverable": deliverable, "plan": plan})


@wf.node(retries=1, timeout=10800)
async def engineering(review, *, branch):
    """Execute the plan step by step, or make the one fix that was asked for.

    A failed step raises rather than dead-letters, which is the opposite
    of every other stage here: the usual failure is a turn truncated at
    the model's output limit, and that is exactly the case a second
    attempt can win — the engineer's prompt tells it to overwrite a
    partial file with a clean scaffold. Rule 3 does the counting
    (``retries`` above); the body only says which class of failure this
    is (04 §Failure classes).
    """

    deliverable = _field_of(branch, "deliverable")
    steps = _steps_of(branch)
    if steps:
        for index, step in enumerate(steps, 1):
            result = await GameEngineerAgent().run(
                _step_assignment(deliverable, step, index, len(steps))
            )
            if not result.ok:
                raise AgentError(
                    f"build step {index}/{len(steps)} ({_field(step, 'name')}) "
                    f"failed: {result.error or result.stop_reason}"
                )
    else:
        result = await GameEngineerAgent().run(_assignment(deliverable))
        if not result.ok:
            raise AgentError(
                f"engineering fix failed: {result.error or result.stop_reason}"
            )
    return review(branch)


@wf.node(retries=1, timeout=3600)
async def review(engineering, human_qa, *, branch):
    """Review the built game; approve it to the playtest or send it back."""

    deliverable = _field_of(branch, "deliverable")
    decision = _submitted(
        await GameReviewerAgent().run(_assignment(deliverable)), ReviewDecision
    )
    if decision.verdict == "approve":
        return human_qa(branch)
    # The loop-back carries the game and not the plan, so engineering
    # reads it as one targeted fix.
    return engineering({"deliverable": deliverable})


@wf.node(retries=1, timeout=600)
async def human_qa(qa, *, branch):
    """Ask the operator to play it, and thread the reply into QA.

    The attempt's pool slot goes back for the duration of the wait, and
    the node's own timeout is paused while it waits (04 §Timeouts) — so
    the 600 s above bounds the work either side of the question, not the
    operator.
    """

    deliverable = _field_of(branch, "deliverable")
    reply = await human_input(
        PLAYTEST_QUESTION.format(file_path=_field(deliverable, "file_path"))
    )
    await current_task().services.log.append(
        f"playtest report: {reply}", author="user", kind="note"
    )
    return qa({**_branch(branch), "human_feedback": reply})


@wf.node(retries=1, timeout=3600)
async def qa(engineering, publish, *, branch):
    """Drive the game in a real browser; approve it to publish or send it back."""

    deliverable = _field_of(branch, "deliverable")
    assignment = _assignment(deliverable)
    feedback = _field_of(branch, "human_feedback")
    if feedback:
        assignment += (
            "\n\nOperator playtest report — it is part of your verdict. If it "
            "reports problems, fail and list them as the fixes needed:\n"
            f"{feedback}"
        )
    decision = _submitted(await QAEngineerAgent().run(assignment), ReviewDecision)
    if decision.verdict == "approve":
        return publish(branch)
    return engineering({"deliverable": deliverable})


@wf.node(retries=1, timeout=60)
async def publish(*, branch):
    """Say where the finished game is. Terminal: no edges, so the branch ends.

    No git: games ship as files, not as commits. The returned path is
    the branch's output, which is what the run carries when the last
    branch finishes (04 §Routing interpretation).
    """

    deliverable = _field_of(branch, "deliverable")
    file_path = _field(deliverable, "file_path")
    await current_task().services.log.append(
        f"game shipped: {file_path} — open it in a browser to play"
        if file_path
        else "game shipped",
        author="engine",
        kind="deliverable",
    )
    return file_path


def _branch(branch: Any) -> dict[str, Any]:
    """The branch payload as a mapping, whatever arrived.

    A task moved onto one of the tail nodes by hand carries whatever the
    operator sent — including nothing — and the tail threads its payload
    forward, so it has to be something that can be spread.
    """

    return dict(branch) if isinstance(branch, dict) else {}


def _field_of(branch: Any, key: str) -> Any:
    """One key of the branch payload, or ``None`` where there is none."""

    return _branch(branch).get(key)


def _steps_of(branch: Any) -> list[Any]:
    """The plan's build steps, or an empty list on a loop-back.

    Review and QA route back with the game alone, and the absence of a
    plan is the signal: engineering runs one fix session rather than the
    whole build again.
    """

    plan = _field_of(branch, "plan")
    if isinstance(plan, ArchitecturePlan):
        return list(plan.steps)
    if isinstance(plan, dict):
        steps = plan.get("steps")
        if isinstance(steps, list):
            return steps
    return []


declare(wf)
