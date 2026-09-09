"""`projects` on the v1 API: triage, the retargeted seats, the threaded cwd.

`feature_build`'s pipeline with a triage stage in front of it, run inside
whichever repository the request belongs to (T075, D65). Three things
make it its own example rather than a copy, and they are what this file
asserts.

**The seats are `feature_build`'s, retargeted.** Each stage class puts
:class:`~projects.ProjectsSeat` in front of `feature_build`'s agent in
the MRO, so the command, the tooling tier and the stats provider come
from the adapter and the prompt and the ``output_model`` come from the
stage. That is checked per stage, in both directions: the prompt is the
one `feature_build` wrote, and nothing of pi's survives.

**Every node runs its agent in the triaged directory.** The project
context is the routing payload, and a branch that lost it would edit the
wrong repository — so each body is run with a context and asserted to
have constructed its agent with that ``cwd``, and asserted to refuse
rather than default when there is none.

**Triage is where the run can go wrong cheaply.** A projects root with
nothing in it, and a model that names a project it was not offered, are
two different failure classes, and the bodies pick between them (04
§Failure classes).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import projects
from athanore import ACPAgent, AgentError, NonRetryable
from athanore.agents.base import Agent, AgentResult
from athanore.engine.context import TaskContext, bind
from athanore.engine.routing import interpret
from athanore.graph import EdgeRef, Graph, Node
from athanore.plugins.discovery import discover
from athanore.store.rows import LogAuthor, LogKind
from athanore.store.uow import Store
from athanore.testing import MockAgent, validate_scenario
from feature_build import (
    ArchitectAgent as _ArchitectAgent,
)
from feature_build import (
    CodeReviewerAgent as _CodeReviewerAgent,
)
from feature_build import (
    Deliverable,
    ProductSpec,
    ReviewDecision,
)
from feature_build import (
    GitEngineerAgent as _GitEngineerAgent,
)
from feature_build import (
    ProductManagerAgent as _ProductManagerAgent,
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
from projects import (
    CLAUDE,
    CLAUDE_ACP_VERSION,
    HAIKU,
    OPUS,
    SONNET,
    ProjectsSeat,
    TriageVerdict,
    known_projects,
    projects_dir,
    wf,
)

GRAPH: Graph = wf.finalize()

#: One node, the seat it runs, and the model that seat declares.
#: ``gate`` is absent: it is the node with no agent.
STAGES: dict[str, tuple[type[Agent], str]] = {
    "triage": (projects.TriageAgent, HAIKU),
    "prompt": (projects.PromptAgent, HAIKU),
    "product": (projects.ProductAgent, SONNET),
    "architecture": (projects.ArchitectAgent, OPUS),
    "engineering": (projects.EngineerAgent, OPUS),
    "review": (projects.ReviewerAgent, OPUS),
    "qa": (projects.QAAgent, SONNET),
    "git": (projects.GitAgent, HAIKU),
}

#: Which `feature_build` stage each seat is a retarget of. ``triage`` has
#: none — it is the stage this workflow adds.
BORROWED: dict[str, type[Agent]] = {
    "prompt": _PromptEngineerAgent,
    "product": _ProductManagerAgent,
    "architecture": _ArchitectAgent,
    "engineering": _SoftwareEngineerAgent,
    "review": _CodeReviewerAgent,
    "qa": _QAEngineerAgent,
    "git": _GitEngineerAgent,
}

PIPELINE: dict[str, tuple[str, ...]] = {
    "triage": ("prompt",),
    "prompt": ("product",),
    "product": ("architecture",),
    "architecture": ("engineering",),
    "engineering": ("review",),
    "review": ("engineering", "qa"),
    "qa": ("engineering", "gate"),
    "gate": ("engineering", "git"),
    "git": (),
}

SCENARIOS = Path(projects.__file__).resolve().parent / "scenarios"

#: The project context every node of the tail is handed and hands on.
WHERE = {"project": "reporter", "cwd": "/projects/reporter"}


def node(name: str) -> Node:
    return GRAPH.nodes[name]


async def route(name: str, payload: Any = None) -> list[tuple[str, Any]]:
    """Run node ``name``'s body and interpret what it returned."""

    one = node(name)
    slot = {one.payload_param: payload} if one.payload_param else {}
    value = await one.fn(*(EdgeRef(edge) for edge in one.edges), **slot)
    return [(step.target, step.payload) for step in interpret(one, value)]


@pytest.fixture
def stage(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[dict[str, Any]]]:
    """Replace one stage's agent class and record how the body built it.

    The substitution is by the name the body reaches for, so it only
    works if the body really runs that seat — and what is recorded is the
    constructor's keyword arguments, because ``cwd`` is the one thing
    this workflow adds to every call.
    """

    def use(name: str, **scripted: Any) -> list[dict[str, Any]]:
        assert isinstance(getattr(projects, name, None), type), name
        built: list[dict[str, Any]] = []

        def make(**kwargs: Any) -> Agent:
            built.append(kwargs)
            return MockAgent(**scripted)

        monkeypatch.setattr(projects, name, make, raising=True)
        return built

    return use


@pytest.fixture
def root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A projects directory with three checkouts and some noise in it."""

    for name in ("reporter", "ledger", "atlas", ".git", "__pycache__"):
        (tmp_path / name).mkdir()
    (tmp_path / "README.md").write_text("not a project", encoding="utf-8")
    monkeypatch.setenv("ATHANORE_PROJECTS_DIR", str(tmp_path))
    return tmp_path


# --------------------------------------------------------------------------
# The graph
# --------------------------------------------------------------------------


def test_the_graph_is_feature_builds_with_triage_in_front() -> None:
    """Signature is the graph (rule 1), and the start node is the new one."""

    assert GRAPH.name == "projects"
    assert GRAPH.start == "triage"
    assert {name: one.edges for name, one in GRAPH.nodes.items()} == PIPELINE
    assert [name for name, one in GRAPH.nodes.items() if not one.edges] == ["git"]


def test_every_node_of_the_tail_carries_the_project_context() -> None:
    """A branch that lost it would run its agent in the wrong repository."""

    slots = {name: one.payload_param for name, one in GRAPH.nodes.items()}
    tail = dict.fromkeys(PIPELINE.keys() - {"triage"}, "project")
    assert slots == {"triage": None, **tail}
    for name in PIPELINE:
        assert "project" not in node(name).edges, name


def test_every_node_declares_its_retries_and_its_timeout() -> None:
    """The metadata seam, used: no body counts its own attempts (rule 3)."""

    for name, one in GRAPH.nodes.items():
        assert one.retries is not None, name
        assert one.timeout is not None and one.timeout > 0, name
    assert node("git").retries == 0


# --------------------------------------------------------------------------
# The seats
# --------------------------------------------------------------------------


def test_the_adapter_is_pinned_and_is_not_pi() -> None:
    """05 §User-land adapters: command and model only, and the pin (12)."""

    assert CLAUDE == [
        "npx",
        "-y",
        f"@agentclientprotocol/claude-agent-acp@{CLAUDE_ACP_VERSION}",
    ]
    assert ProjectsSeat.command == CLAUDE
    # `auto`, so the façade negotiates the `mcp` tier this adapter
    # advertises rather than pi's `native` one, which depends on an
    # extension that is not installed here (05 §Tooling tiers).
    assert ProjectsSeat.tooling == "auto"
    # No session file this package knows how to read, so no provider: what
    # ACP reports is what a stats entry carries, and the rest is omitted
    # rather than estimated (01 §Real data only).
    assert ProjectsSeat.stats_provider is None
    # These agents edit the operator's own repositories with no container
    # around them, so every tool call is asked about (12).
    assert ProjectsSeat.permission_policy == "ask"


@pytest.mark.parametrize("name", sorted(STAGES))
def test_every_seat_is_the_adapter_in_front_of_the_stage(name: str) -> None:
    """The MRO is the retarget: the adapter wins, the stage keeps its prompt."""

    seat, model = STAGES[name]
    assert issubclass(seat, ProjectsSeat), name
    assert seat.command == CLAUDE, name
    assert seat.tooling == "auto", name
    assert seat.stats_provider is None, name
    # The model is declared per stage, on the stage: inheriting one from
    # the other side of the MRO would be inheriting pi's.
    assert vars(seat).get("model") == model, name
    assert seat.model == model, name


@pytest.mark.parametrize("name", sorted(BORROWED))
def test_a_retargeted_seat_keeps_the_prompt_and_the_model_it_borrowed(
    name: str,
) -> None:
    """ "The same prompts, roles and output models" — the same objects."""

    seat, _ = STAGES[name]
    borrowed = BORROWED[name]
    assert issubclass(seat, borrowed), name
    assert seat.system_prompt is borrowed.system_prompt, name
    assert seat.output_model is borrowed.output_model, name
    # And it declares nothing of its own but the model: a seat that
    # carried its own prompt would be a copy that can drift.
    assert {key for key in vars(seat) if not key.startswith("__")} == {"model"}, name


def test_triage_is_the_one_seat_this_workflow_writes_itself() -> None:
    """It has no `feature_build` counterpart, so its prompt is inlined here."""

    assert not any(issubclass(projects.TriageAgent, one) for one in BORROWED.values())
    prompt = vars(projects.TriageAgent).get("system_prompt")
    assert isinstance(prompt, str) and prompt.lstrip().startswith("# Triage")
    assert "triage → prompt → product" in prompt
    assert projects.TriageAgent.output_model is TriageVerdict


def test_a_triage_verdict_is_one_non_empty_name() -> None:
    """The body checks it against the list; the model checks it is a name."""

    from pydantic import ValidationError

    assert TriageVerdict(project="reporter").project == "reporter"
    with pytest.raises(ValidationError):
        TriageVerdict(project="")


def test_nothing_here_is_a_second_athanore_agent_base() -> None:
    """`ProjectsSeat` extends the package's `ACPAgent` and adds two facts."""

    assert ProjectsSeat.__bases__ == (ACPAgent,)


# --------------------------------------------------------------------------
# Where the projects are
# --------------------------------------------------------------------------


def test_the_projects_root_is_the_override_then_the_servers_own(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`ATHANORE_PROJECTS_DIR` wins; otherwise it is `root_path` (02)."""

    monkeypatch.delenv("ATHANORE_PROJECTS_DIR", raising=False)
    monkeypatch.setenv("ATHANORE_ROOT_PATH", str(tmp_path))
    assert projects_dir() == tmp_path
    monkeypatch.setenv("ATHANORE_PROJECTS_DIR", str(tmp_path / "elsewhere"))
    assert projects_dir() == tmp_path / "elsewhere"


def test_the_projects_are_the_visible_directories(root: Path) -> None:
    """Hidden entries, the noise list and plain files are not projects."""

    assert known_projects() == ["atlas", "ledger", "reporter"]


def test_a_root_that_is_not_there_has_no_projects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Read at triage time rather than at import, so this is answerable."""

    monkeypatch.setenv("ATHANORE_PROJECTS_DIR", str(tmp_path / "nope"))
    assert known_projects() == []


# --------------------------------------------------------------------------
# Triage
# --------------------------------------------------------------------------


async def test_triage_picks_a_project_and_hands_its_directory_downstream(
    stage: Callable[..., list[dict[str, Any]]],
    root: Path,
    store: Store,
    context: Callable[..., Any],
) -> None:
    ctx: TaskContext = await context("Add a --json flag", node="triage")
    built = stage("TriageAgent", output=TriageVerdict(project="reporter"))
    with bind(ctx):
        steps = await route("triage")
    assert steps == [("prompt", {"project": "reporter", "cwd": str(root / "reporter")})]
    # The classifier is run at the root, because what it is choosing
    # between is the directories under it.
    assert built == [{"cwd": str(root)}]
    async with store.uow() as uow:
        written = await uow.log.list(ctx.run_id)
    assert [(entry.author, entry.kind, entry.text) for entry in written] == [
        (LogAuthor.engine, LogKind.note, "routed to project: reporter")
    ]


async def test_triage_is_told_the_task_and_the_names_it_may_choose_from(
    monkeypatch: pytest.MonkeyPatch,
    root: Path,
    context: Callable[..., Any],
) -> None:
    """The list is in the prompt, which is what makes an off-list name a bug."""

    seen: list[str] = []

    class Recorder(MockAgent):
        async def run(self, prompt: str = "") -> AgentResult:
            seen.append(prompt)
            return AgentResult(output=TriageVerdict(project="ledger"))

    monkeypatch.setattr(projects, "TriageAgent", lambda **kwargs: Recorder())
    ctx: TaskContext = await context("Add a --json flag", node="triage")
    with bind(ctx):
        await route("triage")
    assert "- reporter" in seen[0] and "- ledger" in seen[0] and "- atlas" in seen[0]
    assert "Add a --json flag" in seen[0]


async def test_a_root_with_no_projects_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    context: Callable[..., Any],
) -> None:
    """Configuration, not inference: no retry finds a project that is not there."""

    monkeypatch.setenv("ATHANORE_PROJECTS_DIR", str(tmp_path / "nope"))
    ctx: TaskContext = await context(node="triage")
    with bind(ctx), pytest.raises(NonRetryable, match="no projects found"):
        await route("triage")


async def test_a_project_that_was_not_offered_is_retryable(
    stage: Callable[..., list[dict[str, Any]]],
    root: Path,
    context: Callable[..., Any],
) -> None:
    """The list was in the prompt, so this is a turn that went wrong."""

    ctx: TaskContext = await context(node="triage")
    stage("TriageAgent", output=TriageVerdict(project="invented"))
    with bind(ctx), pytest.raises(AgentError, match="invented"):
        await route("triage")


# --------------------------------------------------------------------------
# The tail: every agent runs in the triaged directory
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "seat", "scripted"),
    [
        ("prompt", "PromptAgent", {"text": "reworded"}),
        (
            "product",
            "ProductAgent",
            {
                "output": ProductSpec(
                    spec_path="docs/specs/x.md",
                    deliverables=[Deliverable(title="one", description="the first")],
                )
            },
        ),
        ("architecture", "ArchitectAgent", {"text": "planned"}),
        ("engineering", "EngineerAgent", {"text": "implemented"}),
        ("review", "ReviewerAgent", {"output": ReviewDecision(verdict="approve")}),
        ("qa", "QAAgent", {"output": ReviewDecision(verdict="approve")}),
        ("git", "GitAgent", {"text": "committed"}),
    ],
)
async def test_every_agent_stage_runs_in_the_triaged_directory(
    stage: Callable[..., list[dict[str, Any]]],
    name: str,
    seat: str,
    scripted: dict[str, Any],
) -> None:
    built = stage(seat, **scripted)
    payload = {**WHERE, "deliverable": {"title": "one", "description": "the first"}}
    await route(name, payload)
    assert built == [{"cwd": WHERE["cwd"]}]


@pytest.mark.parametrize(
    ("name", "seat", "scripted"),
    [
        ("prompt", "PromptAgent", {"text": "reworded"}),
        ("architecture", "ArchitectAgent", {"text": "planned"}),
        ("engineering", "EngineerAgent", {"text": "implemented"}),
        ("git", "GitAgent", {"text": "committed"}),
    ],
)
async def test_a_task_with_no_project_context_stops_rather_than_defaulting(
    stage: Callable[..., list[dict[str, Any]]],
    name: str,
    seat: str,
    scripted: dict[str, Any],
) -> None:
    """Running the engineer in the server's own directory is the one
    failure this workflow must not have, so a lost context is a dead
    letter and never a default."""

    stage(seat, **scripted)
    with pytest.raises(NonRetryable, match="no project context"):
        await route(name, None)


async def test_the_tail_threads_the_context_and_nothing_else(
    stage: Callable[..., list[dict[str, Any]]],
) -> None:
    """A payload cannot accumulate a stage's leftovers on its way down."""

    stage("PromptAgent", text="reworded")
    assert await route("prompt", {**WHERE, "leftover": "junk"}) == [("product", WHERE)]


async def test_the_product_stage_fans_out_with_the_context_on_every_branch(
    stage: Callable[..., list[dict[str, Any]]],
) -> None:
    """One branch per deliverable, each still knowing where it is."""

    stage(
        "ProductAgent",
        output=ProductSpec(
            spec_path="docs/specs/two.md",
            deliverables=[
                Deliverable(title="one", description="the first"),
                Deliverable(title="two", description="the second"),
            ],
        ),
    )
    assert await route("product", WHERE) == [
        (
            "architecture",
            {**WHERE, "deliverable": {"title": "one", "description": "the first"}},
        ),
        (
            "architecture",
            {**WHERE, "deliverable": {"title": "two", "description": "the second"}},
        ),
    ]


async def test_the_branch_deliverable_reaches_the_architect_as_the_assignment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one thing this branch is told that its siblings are not (19)."""

    seen: list[str] = []

    class Recorder(MockAgent):
        async def run(self, prompt: str = "") -> AgentResult:
            seen.append(prompt)
            return AgentResult()

    monkeypatch.setattr(projects, "ArchitectAgent", lambda **kwargs: Recorder())
    payload = {**WHERE, "deliverable": {"title": "one", "description": "the first"}}
    assert await route("architecture", payload) == [("engineering", WHERE)]
    assert seen == ["Deliverable for this branch: one. the first"]
    # A task moved onto the node by hand simply adds no section.
    assert projects._assignment(None) == ""


@pytest.mark.parametrize(
    ("name", "seat", "approved", "rejected"),
    [
        ("review", "ReviewerAgent", "qa", "engineering"),
        ("qa", "QAAgent", "gate", "engineering"),
    ],
)
@pytest.mark.parametrize("verdict", ["approve", "changes_requested"])
async def test_the_verdicts_route_and_keep_the_context(
    stage: Callable[..., list[dict[str, Any]]],
    name: str,
    seat: str,
    approved: str,
    rejected: str,
    verdict: str,
) -> None:
    stage(seat, output=ReviewDecision(verdict=verdict))  # type: ignore[arg-type]
    target = approved if verdict == "approve" else rejected
    assert await route(name, WHERE) == [(target, WHERE)]


async def test_the_git_stage_ends_the_branch_with_what_it_reported(
    stage: Callable[..., list[dict[str, Any]]],
) -> None:
    """No edges, so the value is the branch's — and the run's — output."""

    stage("GitAgent", text="committed 9c31ae4")
    assert await route("git", WHERE) == []
    assert await node("git").fn(project=WHERE) == "committed 9c31ae4"


async def test_a_refused_agent_dead_letters_rather_than_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed result is returned, not raised; the body decides (05)."""

    class Refusing(MockAgent):
        async def run(self, prompt: str = "") -> AgentResult:
            return AgentResult(
                status="failed", error="I will not", stop_reason="refusal"
            )

    monkeypatch.setattr(projects, "EngineerAgent", lambda **kwargs: Refusing())
    with pytest.raises(NonRetryable, match="I will not"):
        await route("engineering", WHERE)


# --------------------------------------------------------------------------
# The gate: the one verdict no model gets a say in
# --------------------------------------------------------------------------


async def test_the_gate_runs_in_the_project_and_sends_green_to_git(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    store: Store,
    context: Callable[..., Any],
) -> None:
    """The exit code decides, and the suite that produced it is the project's."""

    ctx: TaskContext = await context(node="gate")
    monkeypatch.setattr(projects, "GATE_COMMAND", ("sh", "-c", "pwd; echo '3 passed'"))
    where = {"project": "reporter", "cwd": str(tmp_path)}
    with bind(ctx):
        assert await route("gate", where) == [("git", where)]
    async with store.uow() as uow:
        written = await uow.log.list(ctx.run_id)
    assert written[0].kind == LogKind.note
    assert written[0].text.startswith("test gate [reporter]: PASS")
    assert "3 passed" in written[0].text
    # It really ran there: the command printed the directory it was in.
    assert str(tmp_path) in written[0].text


async def test_the_gate_sends_a_red_suite_back_with_its_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    store: Store,
    context: Callable[..., Any],
) -> None:
    ctx: TaskContext = await context(node="gate")
    monkeypatch.setattr(
        projects, "GATE_COMMAND", ("sh", "-c", "echo 'E   assert 1 == 2'; exit 1")
    )
    where = {"project": "reporter", "cwd": str(tmp_path)}
    with bind(ctx):
        assert await route("gate", where) == [("engineering", where)]
    async with store.uow() as uow:
        written = await uow.log.list(ctx.run_id)
    assert written[0].kind == LogKind.failure
    assert written[0].text.startswith("test gate [reporter]: FAIL")
    assert "assert 1 == 2" in written[0].text


async def test_a_gate_command_that_is_not_installed_stops_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, context: Callable[..., Any]
) -> None:
    """Retrying spawns the same missing executable, so it does not retry."""

    ctx: TaskContext = await context(node="gate")
    monkeypatch.setattr(projects, "GATE_COMMAND", ("athanore-no-such-command",))
    where = {"project": "reporter", "cwd": str(tmp_path)}
    with bind(ctx), pytest.raises(NonRetryable, match="athanore-no-such-command"):
        await route("gate", where)


async def test_a_gate_whose_project_is_gone_stops_the_run(
    tmp_path: Path, context: Callable[..., Any]
) -> None:
    """The same refusal, for the other half of "could not be run".

    A checkout the operator moved or deleted between the triage and the
    gate is not a failing suite: it is a directory that is not there, and
    no retry puts it back.
    """

    ctx: TaskContext = await context(node="gate")
    where = {"project": "reporter", "cwd": str(tmp_path / "gone")}
    with bind(ctx), pytest.raises(NonRetryable, match="could not be run in"):
        await route("gate", where)


def test_the_gate_output_is_capped() -> None:
    """A megabyte of pytest output is not a work-log entry."""

    assert projects.GATE_TAIL == 1500
    assert projects.GATE_COMMAND == ("uv", "run", "pytest", "-q")


# --------------------------------------------------------------------------
# Discovery and the scenarios
# --------------------------------------------------------------------------


def test_athanore_serve_discovers_projects() -> None:
    """`athanore serve` needs to be told nothing (09 §Discovery)."""

    found = {workflow.name: workflow for workflow in discover()}
    assert found["projects"] is wf


def test_every_agent_stage_ships_a_scenario() -> None:
    """13 §Running examples on the fake: one per agent node, plus the default."""

    assert {path.name for path in SCENARIOS.glob("*.json")} == {
        "default.json",
        *(f"projects.{name}.json" for name in STAGES),
    }


@pytest.mark.parametrize("path", sorted(SCENARIOS.glob("*.json")), ids=lambda p: p.name)
def test_a_scenario_scripts_the_stage_it_is_named_for(path: Path) -> None:
    """Valid against 13's vocabulary, and against the stage's own model."""

    scripted = validate_scenario(
        json.loads(path.read_text(encoding="utf-8")), where=path.name
    )
    if path.name == "default.json":
        assert "submit" not in scripted
        return
    stage_name = path.stem.split(".", 1)[1]
    seat, _ = STAGES[stage_name]
    assert scripted["log"].startswith(f"{stage_name}: ")
    model = seat.output_model
    if model is None:
        assert "submit" not in scripted, stage_name
    else:
        assert model.model_validate(scripted["submit"])
