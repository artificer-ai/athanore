"""projects — one athanore server over many repositories.

The server is pointed at a *projects directory* — the parent of many
checkouts — and a triage node reads the submitted request, picks the one
project it belongs to, and runs the rest of the pipeline **inside that
project's directory**. Every stage's agent therefore starts where that
project's own configuration is, and picks it up.

    triage → prompt → product → architecture → engineering
                          │           ▲
                          └ fan-out ─┐│
                                     ▼│
                          → review ⇄ qa → gate → git

The tail is `feature_build`'s, and so are its stages: the same prompts,
the same roles and the same output models, **retargeted to a different
adapter**. That is what these seats are — each is `feature_build`'s
agent class with :class:`ProjectsSeat` in front of it in the MRO, so the
prompt and the ``output_model`` come from the stage and the command, the
tier and the stats provider come from the seat. Nothing here is
Claude-specific beyond those two lines: ``cwd`` is an ordinary
``ACPAgent`` argument, so pointing these at pi instead is one edit.

**What flows where.** State flows through the run's work log, exactly as
in `feature_build`. The routing payload carries the one thing the log
cannot: the project this run was triaged to, and the directory it lives
in — threaded through every transition, every fan-out branch, every
retry and every loop-back, because a branch that lost it would run its
agent in the wrong repository.

**Where the projects are.** ``ATHANORE_PROJECTS_DIR`` if it is set,
otherwise the server's ``root_path`` (``ATHANORE_ROOT_PATH`` or
``athanore.toml``, 02 §Settings), which defaults to the directory the
server was started in.

Submit work with the CLI::

    athanore submit projects "Add a retry button" "As a user I want ..."
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, Field

from athanore import (
    ACPAgent,
    AgentError,
    AgentResult,
    NonRetryable,
    Workflow,
    current_task,
)
from athanore.settings import AthanoreSettings
from feature_build import (
    ArchitectAgent as _ArchitectAgent,
)
from feature_build import (
    CodeReviewerAgent as _CodeReviewerAgent,
)
from feature_build import (
    GitEngineerAgent as _GitEngineerAgent,
)
from feature_build import (
    ProductManagerAgent as _ProductManagerAgent,
)
from feature_build import (
    ProductSpec,
    ReviewDecision,
)
from feature_build import (
    PromptEngineerAgent as _PromptEngineerAgent,
)
from feature_build import (
    QAEngineerAgent as _QAEngineerAgent,
)
from feature_build import (
    SoftwareEngineerAgent as _SoftwareEngineerAgent,
)

__all__ = [
    "CLAUDE",
    "CLAUDE_ACP_VERSION",
    "GATE_COMMAND",
    "GATE_TAIL",
    "HAIKU",
    "OPUS",
    "SKIP",
    "SONNET",
    "ArchitectAgent",
    "EngineerAgent",
    "GitAgent",
    "ProductAgent",
    "ProjectsSeat",
    "PromptAgent",
    "QAAgent",
    "ReviewerAgent",
    "TriageAgent",
    "TriageVerdict",
    "known_projects",
    "projects_dir",
    "wf",
]

M = TypeVar("M", bound=BaseModel)

#: The Claude Code ACP adapter, pinned rather than floating: an example
#: that runs `npx -y @agentclientprotocol/claude-agent-acp` picks up
#: whatever was published this morning (12 §Supply chain). It matches
#: ``CLAUDE_ACP_VERSION`` in `compose.yaml`, which is the same adapter
#: inside the dev sandbox.
CLAUDE_ACP_VERSION = "0.75.1"

#: The command every seat here spawns.
CLAUDE = ["npx", "-y", f"@agentclientprotocol/claude-agent-acp@{CLAUDE_ACP_VERSION}"]

#: The model ids this adapter advertises. An id it does not know is not
#: silently swapped for its default — the façade resolves ``model`` as a
#: config option by category and logs the rejection into the transcript
#: (20 §Finding 2) — so these are the four words that work.
OPUS = "opus[1m]"
SONNET = "sonnet"
HAIKU = "haiku"

#: What the deterministic gate runs, in the **triaged project's**
#: directory. A constant rather than a setting, for the reason
#: `feature_build`'s is: a pipeline whose gate is configurable is a
#: pipeline whose gate can be configured away.
GATE_COMMAND = ("uv", "run", "pytest", "-q")

#: How much of the gate's output reaches the work log.
GATE_TAIL = 1500

#: Directory names that are never a project. Everything hidden is
#: skipped too — a projects root is somebody's home for repositories,
#: not a curated list.
SKIP = frozenset({"__pycache__", "node_modules"})


def projects_dir() -> Path:
    """Where the projects live.

    ``ATHANORE_PROJECTS_DIR`` wins, because a server may well be anchored
    (database, token file) somewhere other than the directory the
    repositories are in. Otherwise it is the server's own ``root_path``,
    read through the settings object rather than off the environment, so
    that ``athanore.toml`` counts here exactly as it does everywhere else
    (02 §Settings).
    """

    override = os.environ.get("ATHANORE_PROJECTS_DIR")
    if override:
        return Path(override).expanduser()
    return AthanoreSettings().root_path


def known_projects() -> list[str]:
    """The project directory names, sorted; empty where there is no root.

    Read at the moment triage runs rather than at import: a projects
    directory gains and loses checkouts while the server is up, and a
    list captured at startup would be one the operator cannot refresh.
    """

    root = projects_dir()
    if not root.is_dir():
        return []
    return sorted(
        entry.name
        for entry in root.iterdir()
        if entry.is_dir() and not entry.name.startswith(".") and entry.name not in SKIP
    )


class ProjectsSeat(ACPAgent):
    """The adapter half of every seat here: Claude Code over ACP.

    Listed **first** in each stage's bases, so it wins over the pi seat
    `feature_build`'s classes carry: the command, the tooling tier and
    the stats provider are facts about the adapter, and the prompt and
    the ``output_model`` are facts about the stage. Each stage still
    declares its own ``model``, because the model is a per-stage
    decision and inheriting one from the other side of the MRO would be
    inheriting pi's.

    ``tooling`` is left at ``auto``: this adapter advertises MCP, so the
    façade negotiates the ``mcp`` tier and the task token never reaches
    the prompt (05 §Tooling tiers). ``permission_policy`` is left at
    ``ask``, which is the whole difference between this seat and a
    sandboxed one — these agents edit the operator's own repositories,
    with no container around them, so every tool call the adapter asks
    about is asked about (05 §Permissions, 12).
    """

    command = CLAUDE
    tooling = "auto"
    permission_policy = "ask"
    #: Claude Code keeps no session file this package knows how to read,
    #: so there is no provider to name. The ACP ``usage`` the adapter
    #: reports is what a stats entry carries, and what it does not report
    #: is omitted rather than estimated (01 §Real data only).
    stats_provider = None


class TriageVerdict(BaseModel):
    """Which project a request belongs to: exactly one directory name."""

    project: str = Field(
        min_length=1,
        description="The exact directory name, from the list in the prompt.",
    )


class TriageAgent(ProjectsSeat):
    """A cheap classifier: map one request onto one known project."""

    model = HAIKU
    output_model = TriageVerdict
    system_prompt = """# Triage

You are the triage stage of an athanore workflow pipeline that runs a
feature pipeline inside one of several projects:

triage → prompt → product → architecture → engineering → review ⇄ qa → gate → git

You are given a task and the list of available project directory names, and
you decide which single project the task belongs to.

## How this pipeline works (important)

- **Start by reading your task.** The `## Your task` block at the end of this
  message says how — a tool your harness gave you, or a `curl` line. It
  returns the title, description, and the FULL work log — deliverables and
  notes from every earlier stage and attempt. **Before you finish, append
  your deliverable to the run's work log** the same way — the next stage
  reads this same log.
- Routing is automatic: when you finish, the engine runs the rest of the
  pipeline inside the project you chose. You never create tasks, move tasks,
  or call any workflow API.
- If structured output instructions are appended to the end of this message,
  follow them exactly.

## Your job

1. Read the task and the list of project directory names in this message.
2. Look at the projects only as far as you need to decide — a README, a
   directory listing. **Do not edit any file.**
3. Choose exactly one. Use the exact directory name from the list; do not
   invent a name, do not return more than one, and do not return none.

## Deliverable (structured submission)

Append a one-line log entry saying which project you chose and why, and
submit the choice the way the instructions appended to this message
describe.

## If blocked

If no project in the list can plausibly own the task, say so as your entire
output rather than choosing at random — a run in the wrong repository is
worse than a run that stopped.
"""


class PromptAgent(ProjectsSeat, _PromptEngineerAgent):
    """`feature_build`'s intake stage, on this adapter."""

    model = HAIKU


class ProductAgent(ProjectsSeat, _ProductManagerAgent):
    """`feature_build`'s product stage, on this adapter."""

    model = SONNET


class ArchitectAgent(ProjectsSeat, _ArchitectAgent):
    """`feature_build`'s architecture stage, on this adapter."""

    model = OPUS


class EngineerAgent(ProjectsSeat, _SoftwareEngineerAgent):
    """`feature_build`'s engineering stage, on this adapter."""

    model = OPUS


class ReviewerAgent(ProjectsSeat, _CodeReviewerAgent):
    """`feature_build`'s review stage, on this adapter."""

    model = OPUS


class QAAgent(ProjectsSeat, _QAEngineerAgent):
    """`feature_build`'s QA stage, on this adapter."""

    model = SONNET


class GitAgent(ProjectsSeat, _GitEngineerAgent):
    """`feature_build`'s git stage, on this adapter."""

    model = HAIKU


def _completed(result: AgentResult) -> AgentResult:
    """``result``, or a dead letter (04 §Failure classes)."""

    if result.ok:
        return result
    raise NonRetryable(
        result.error or f"the agent stopped: {result.stop_reason or 'no reason given'}"
    )


def _submitted(result: AgentResult, model: type[M]) -> M:
    """The validated submission of a completed run, typed."""

    output = _completed(result).output
    if isinstance(output, model):
        return output
    raise NonRetryable(
        f"expected a {model.__name__} submission, got "
        f"{type(output).__name__}: {output!r}"
    )


def _where(project: Any) -> dict[str, str]:
    """The project context, threaded onward and nothing else.

    Every node returns this and only this, so a payload cannot
    accumulate a stage's leftovers on its way down the pipeline. The
    fan-out is the one place a key is added, and the branch drops it
    again at the next hop.
    """

    return {"project": _key(project, "project"), "cwd": _key(project, "cwd")}


def _key(project: Any, key: str) -> str:
    """One key of the project context, or ``""`` where there is none.

    Payloads are coerced with ``jsonable()`` (04 §Routing interpretation)
    and an operator may move a task onto any of these nodes by hand, so
    the context is read defensively — and :func:`_cwd` is what refuses
    when the missing key is the one that decides where an agent runs.
    """

    if isinstance(project, dict):
        value = project.get(key)
        return str(value) if value is not None else ""
    return ""


def _cwd(project: Any) -> str:
    """The directory this branch's agents run in.

    A dead letter rather than a default when it is missing: running the
    engineer in the server's own directory because a payload lost its
    context would edit the wrong repository, and no retry improves it.
    """

    cwd = _key(project, "cwd")
    if not cwd:
        raise NonRetryable(
            "this task carries no project context; move it onto `triage` to "
            'have one chosen, or send `{"project": ..., "cwd": ...}` with it'
        )
    return cwd


wf = Workflow("projects")


@wf.node(start=True, retries=1, timeout=900)
async def triage(prompt):
    """Read the request, pick a project, and hand its directory downstream."""

    ctx = current_task()
    run = await ctx.services.run.get()
    projects = known_projects()
    if not projects:
        # Not a model's failure and not one a retry fixes: the server is
        # pointed at a directory that holds no projects.
        raise NonRetryable(
            f"no projects found under {projects_dir()} — set "
            "ATHANORE_PROJECTS_DIR or ATHANORE_ROOT_PATH, or start the "
            "server in the directory the projects are in"
        )

    verdict = _submitted(
        await TriageAgent(cwd=str(projects_dir())).run(
            "Available projects (exact directory names):\n"
            + "\n".join(f"- {name}" for name in projects)
            + f"\n\nTask:\n{run.title}\n{run.description}".rstrip()
        ),
        TriageVerdict,
    )
    if verdict.project not in projects:
        # Retryable on purpose: the list is in the prompt, so a name that
        # is not on it is a turn that went wrong rather than a pipeline
        # that cannot work, and the node's `retries` decides how many of
        # those to spend (rule 3).
        raise AgentError(
            f"triage chose {verdict.project!r}, which is not one of the "
            f"projects it was given: {', '.join(projects)}"
        )

    await ctx.services.log.append(
        f"routed to project: {verdict.project}", author="engine", kind="note"
    )
    return prompt(
        {"project": verdict.project, "cwd": str(projects_dir() / verdict.project)}
    )


@wf.node(retries=1, timeout=600)
async def prompt(product, *, project):
    """Reword the raw brief into a well-formed task description."""

    _completed(await PromptAgent(cwd=_cwd(project)).run())
    return product(_where(project))


@wf.node(retries=1, timeout=1800)
async def product(architecture, *, project):
    """Write the spec, and split it into one deliverable per branch."""

    spec = _submitted(await ProductAgent(cwd=_cwd(project)).run(), ProductSpec)
    # The one place a key is added to the payload: each branch carries
    # the project context *and* the deliverable that tells it apart.
    return [
        architecture({**_where(project), "deliverable": one.model_dump()})
        for one in spec.deliverables
    ]


@wf.node(retries=1, timeout=1800)
async def architecture(engineering, *, project):
    """Turn this branch's deliverable into an implementation plan."""

    _completed(
        await ArchitectAgent(cwd=_cwd(project)).run(
            _assignment(_key_value(project, "deliverable"))
        )
    )
    return engineering(_where(project))


@wf.node(retries=1, timeout=10800)
async def engineering(review, *, project):
    """Implement the plan, or fix what review, QA or the gate found."""

    _completed(await EngineerAgent(cwd=_cwd(project)).run())
    return review(_where(project))


@wf.node(retries=1, timeout=3600)
async def review(engineering, qa, *, project):
    """Review the change; approve it to QA or send it back."""

    decision = _submitted(await ReviewerAgent(cwd=_cwd(project)).run(), ReviewDecision)
    target = qa if decision.verdict == "approve" else engineering
    return target(_where(project))


@wf.node(retries=1, timeout=3600)
async def qa(engineering, gate, *, project):
    """Exercise the feature; approve it to the gate or send it back."""

    decision = _submitted(await QAAgent(cwd=_cwd(project)).run(), ReviewDecision)
    target = gate if decision.verdict == "approve" else engineering
    return target(_where(project))


@wf.node(retries=1, timeout=3600)
async def gate(engineering, git, *, project):
    """Run the project's test suite, in the project, and route on the exit code.

    No agent: green goes to git, red goes back to engineering with the
    output. The one verdict in the pipeline that no model gets a say in.
    """

    cwd = _cwd(project)
    try:
        process = await asyncio.create_subprocess_exec(
            *GATE_COMMAND,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except OSError as exc:
        # The command is not on this machine, or the directory is gone.
        # Retrying spawns the same missing executable, so the run stops
        # here and says which one and where.
        raise NonRetryable(
            f"the gate command {' '.join(GATE_COMMAND)} could not be run "
            f"in {cwd}: {exc}"
        ) from exc
    stdout, _ = await process.communicate()
    passed = process.returncode == 0
    tail = stdout.decode(errors="replace").rstrip()[-GATE_TAIL:]

    verdict = "PASS" if passed else "FAIL"
    await current_task().services.log.append(
        f"test gate [{_key(project, 'project')}]: {verdict}\n{tail}",
        author="engine",
        kind="note" if passed else "failure",
    )
    target = git if passed else engineering
    return target(_where(project))


@wf.node(retries=0, timeout=900)
async def git(*, project):
    """Commit the verified change. Terminal: no edges, so the branch ends.

    ``retries=0`` because a commit is not idempotent: an attempt that
    failed after writing one is not repaired by writing it again.
    """

    return _completed(await GitAgent(cwd=_cwd(project)).run()).text


def _key_value(project: Any, key: str) -> Any:
    """One raw key of the payload — the deliverable, which is not a string."""

    return project.get(key) if isinstance(project, dict) else None


def _assignment(deliverable: Any) -> str:
    """The one deliverable this branch is for, as the assignment section.

    The same shape `feature_build`'s has, because it is the same stage
    reading it: a branch that was moved onto by hand simply adds no
    section, since the spec and the split are in the work log (19
    §Assembly).
    """

    if not isinstance(deliverable, dict):
        return ""
    described = ". ".join(
        str(deliverable.get(key, ""))
        for key in ("title", "description")
        if deliverable.get(key)
    )
    return f"Deliverable for this branch: {described}" if described else ""
