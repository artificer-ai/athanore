"""`feature_build` on the v1 API: the graph, the prompts, and the models.

The MVP's starter pipeline, rewritten against `athanore` v1 (T074, D65).
What this file asserts is what the example *declares*, because that is
what an example is: a graph an engine will dispatch, seven prompts a
model will read, and the three models that make two of the stages'
answers routable.

Three things are worth saying about how it asserts them.

**The bodies are run, not read.** ``wf.node`` returns the function
unchanged, so every node body is directly callable; each routing test
calls one with real :class:`~athanore.graph.EdgeRef` arguments and hands
what comes back to :func:`~athanore.engine.routing.interpret` — the
runner's own function, not a restatement of it. A body that returned the
wrong edge, or a value the engine would refuse, fails here rather than in
a run.

**The agents are replaced by name.** The routing tests monkeypatch
``feature_build.CodeReviewerAgent`` and its siblings with a
:class:`~athanore.testing.MockAgent`, so :data:`STAGES` — the table
mapping a node to the seat it runs — is checked against the bodies rather
than asserted beside them: a body that instantiated a different class
would run a real subprocess and fail.

**The scenarios are part of the example.** 13 §Running examples on the
fake requires one per node under ``examples/<wf>/scenarios/``, each of
which logs a deliverable and submits something the node's ``output_model``
accepts. They are validated here against that vocabulary and against
those models, so a scenario cannot rot away from the workflow it scripts.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import feature_build
from athanore import NonRetryable
from athanore.agents.base import Agent, AgentResult
from athanore.engine.context import TaskContext, bind
from athanore.engine.routing import interpret
from athanore.graph import EdgeRef, Graph, Node
from athanore.plugins.discovery import GROUP, discover
from athanore.server import Server
from athanore.store.rows import LogAuthor, LogEntryRow, LogKind
from athanore.store.uow import Store
from athanore.testing import MockAgent, validate_scenario
from feature_build import (
    ArchitectAgent,
    CodeReviewerAgent,
    Deliverable,
    FeatureBuildAgent,
    GitEngineerAgent,
    ProductManagerAgent,
    ProductSpec,
    PromptEngineerAgent,
    QAEngineerAgent,
    ReviewDecision,
    SoftwareEngineerAgent,
    wf,
)
from pi import PI_ACP_VERSION, PiSessionStats

ROOT = Path(__file__).resolve().parents[2]

#: The distribution that ships the examples, as its metadata names it.
DISTRIBUTION = "athanore-examples"

#: One node, one seat. ``gate`` is deliberately absent: it is the node
#: with no agent, and that is the point of it.
STAGES: dict[str, type[Agent]] = {
    "prompt": PromptEngineerAgent,
    "product": ProductManagerAgent,
    "architecture": ArchitectAgent,
    "engineering": SoftwareEngineerAgent,
    "review": CodeReviewerAgent,
    "qa": QAEngineerAgent,
    "git": GitEngineerAgent,
}

#: The pipeline, as the docstring of the workflow draws it: every node
#: and the successors its signature declares.
PIPELINE: dict[str, tuple[str, ...]] = {
    "prompt": ("product",),
    "product": ("architecture",),
    "architecture": ("engineering",),
    "engineering": ("review",),
    "review": ("engineering", "qa"),
    "qa": ("engineering", "gate"),
    "gate": ("engineering", "git"),
    "git": (),
}

SCENARIOS = Path(feature_build.__file__).resolve().parent / "scenarios"

GRAPH: Graph = wf.finalize()


def node(name: str) -> Node:
    """One finalized node of the workflow."""

    return GRAPH.nodes[name]


async def route(name: str, payload: Any = None) -> list[tuple[str, Any]]:
    """Run node ``name``'s body and interpret what it returned.

    The runner's own two steps: call the body with an
    :class:`~athanore.graph.EdgeRef` per declared successor (and the
    payload in its slot, when it has one), then ask
    :func:`~athanore.engine.routing.interpret` what that means. What
    comes back is what would be enqueued.
    """

    one = node(name)
    slot = {one.payload_param: payload} if one.payload_param else {}
    value = await one.fn(*(EdgeRef(edge) for edge in one.edges), **slot)
    return [(step.target, step.payload) for step in interpret(one, value)]


async def entries(store: Store, ctx: TaskContext) -> list[LogEntryRow]:
    """The work-log entries one attempt wrote, oldest first.

    Read back out of the store rather than off the service that wrote
    them: what a loop-back hands the engineer is the row, not the call.
    """

    async with store.uow() as uow:
        return await uow.log.list(ctx.run_id)


@pytest.fixture
def stage(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Replace one stage's agent class with a double the test scripts.

    By the name the body reaches for, so the substitution only works if
    the body really does run that seat: a body that instantiated some
    other class would spawn a real `pi` and fail. ``agent=`` takes a
    zero-argument factory for the two tests that need more than a
    :class:`~athanore.testing.MockAgent` script.
    """

    def use(
        name: str, *, agent: Callable[[], Agent] | None = None, **scripted: Any
    ) -> None:
        assert isinstance(getattr(feature_build, name, None), type), name
        build = agent if agent is not None else (lambda: MockAgent(**scripted))
        monkeypatch.setattr(feature_build, name, build, raising=True)

    return use


# --------------------------------------------------------------------------
# The graph
# --------------------------------------------------------------------------


def test_the_graph_is_the_pipeline() -> None:
    """Signature is the graph: every edge is a parameter name (rule 1)."""

    assert GRAPH.name == "feature_build"
    assert GRAPH.start == "prompt"
    assert {name: one.edges for name, one in GRAPH.nodes.items()} == PIPELINE


def test_the_verdicts_loop_back_to_engineering() -> None:
    """Review, QA and the gate each hold the edge that sends work back."""

    for name in ("review", "qa", "gate"):
        assert "engineering" in node(name).edges, name
    # And engineering is reachable again from each of them, which is what
    # makes the loop a loop rather than three dead edges.
    assert node("engineering").edges == ("review",)


def test_git_is_the_only_terminal_node() -> None:
    """No edges is how a branch ends (04 §Routing interpretation)."""

    terminal = sorted(name for name, one in GRAPH.nodes.items() if not one.edges)
    assert terminal == ["git"]


def test_the_fan_out_is_the_only_payload_in_the_graph() -> None:
    """State flows through the work log; one branch key flows as data."""

    slots = {name: one.payload_param for name, one in GRAPH.nodes.items()}
    assert slots == {
        "prompt": None,
        "product": None,
        "architecture": "deliverable",
        "engineering": None,
        "review": None,
        "qa": None,
        "gate": None,
        "git": None,
    }
    # Keyword-only, so it cannot be mistaken for an edge (04 §Signature
    # parsing).
    assert "deliverable" not in node("architecture").edges


def test_every_node_declares_its_retries_and_its_timeout() -> None:
    """The metadata seam, used: no body counts its own attempts (rule 3)."""

    for name, one in GRAPH.nodes.items():
        assert one.retries is not None, name
        assert one.timeout is not None and one.timeout > 0, name
    # A commit is not idempotent, so the one node that writes history is
    # the one node that is never attempted twice.
    assert node("git").retries == 0
    assert all(node(name).retries == 1 for name in PIPELINE if name != "git")


def test_the_ui_graph_gets_a_description_from_every_body() -> None:
    """`label`/`description` fall back to the name and the docstring."""

    for name, one in GRAPH.nodes.items():
        assert one.label == name
        assert one.description, name


# --------------------------------------------------------------------------
# The prompts
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(STAGES))
def test_every_prompt_is_inlined_on_its_own_class(name: str) -> None:
    """`AGENTS.md`: agent prompts are inlined text on agent classes.

    On the class itself, not inherited from the seat: each stage's prompt
    is the stage, and one that fell back to a base class's would be a
    stage running somebody else's instructions.
    """

    seat = STAGES[name]
    prompt = vars(seat).get("system_prompt")
    assert isinstance(prompt, str) and prompt.strip(), name
    assert prompt.lstrip().startswith("# "), name
    # It names the pipeline it belongs to, which is how a model reading
    # one stage knows what happens either side of it.
    assert "prompt → product → architecture" in prompt, name


@pytest.mark.parametrize("name", sorted(STAGES))
def test_no_stage_loads_its_prompt_from_a_file(name: str) -> None:
    """`template=` is gone (05 §Agent classes) and nothing replaced it.

    The MVP could read a prompt off disk. v1 does not, and an example is
    where that would come back first, so the module that defines a seat
    is asserted to open nothing.
    """

    seat = STAGES[name]
    module = importlib.import_module(seat.__module__)
    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("open(", "read_text", "Template", "loads(", "importlib"):
        assert forbidden not in source, f"{name} reaches for {forbidden}"


# --------------------------------------------------------------------------
# The models
# --------------------------------------------------------------------------


def test_an_output_model_is_declared_wherever_the_graph_routes_on_one() -> None:
    """Rule 2 with a shape: a decision the engine reads is a model.

    Both branching agent nodes route on a `ReviewDecision`, and the
    fan-out routes on the deliverable list of a `ProductSpec`. The four
    stages that only hand work on declare nothing: their deliverable is
    the work log, and a model there would be a schema for prose.
    """

    declared = {name: STAGES[name].output_model for name in STAGES}
    assert declared == {
        "prompt": None,
        "product": ProductSpec,
        "architecture": None,
        "engineering": None,
        "review": ReviewDecision,
        "qa": ReviewDecision,
        "git": None,
    }
    # Every node with a choice to make has a model behind it; `gate` is
    # the exception, and it makes its choice out of an exit code.
    branching = {name for name, one in GRAPH.nodes.items() if len(one.edges) > 1}
    assert branching == {"review", "qa", "gate"}
    assert all(STAGES[name].output_model is not None for name in branching - {"gate"})


def test_a_spec_with_no_deliverables_is_refused() -> None:
    """The fan-out cannot be empty: `return []` would end the run silently."""

    with pytest.raises(ValidationError):
        ProductSpec(spec_path="docs/specs/x.md", deliverables=[])
    one = ProductSpec(
        spec_path="docs/specs/x.md",
        deliverables=[Deliverable(title="t", description="d")],
    )
    assert len(one.deliverables) == 1


def test_a_verdict_is_one_of_two_words() -> None:
    """The node branches on it, so it may not be free text."""

    assert ReviewDecision(verdict="approve").feedback == ""
    with pytest.raises(ValidationError):
        ReviewDecision(verdict="looks fine")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# The seat
# --------------------------------------------------------------------------


def test_every_stage_sits_in_the_one_pinned_pi_seat() -> None:
    """05 §User-land adapters: the vendor knowledge is in `examples/`.

    The command is pinned rather than floating (12 §Supply chain), the
    stats provider is pi's, and every stage runs the one model — which is
    why the workflow is registered on a capacity-1 pool.
    """

    assert FeatureBuildAgent.command == ["npx", "-y", f"pi-acp@{PI_ACP_VERSION}"]
    assert isinstance(FeatureBuildAgent.stats_provider, PiSessionStats)
    assert FeatureBuildAgent.tooling == "native"
    assert FeatureBuildAgent.model == feature_build.MODEL
    for name, seat in STAGES.items():
        assert issubclass(seat, FeatureBuildAgent), name
        assert seat.model == feature_build.MODEL, name
        # A stage is a prompt and, sometimes, a model. Nothing else: a
        # stage that carried its own command would be a second seat.
        declared = {key for key in vars(seat) if not key.startswith("__")}
        assert declared <= {"system_prompt", "output_model"}, name


# --------------------------------------------------------------------------
# The routing (the bodies, run)
# --------------------------------------------------------------------------


async def test_intake_hands_straight_on(stage: Callable[..., None]) -> None:
    stage("PromptEngineerAgent", text="reworded")
    assert await route("prompt") == [("product", None)]


async def test_the_product_stage_fans_out_one_branch_per_deliverable(
    stage: Callable[..., None],
) -> None:
    """Called refs carry the payload that tells the branches apart."""

    stage(
        "ProductManagerAgent",
        output=ProductSpec(
            spec_path="docs/specs/two.md",
            deliverables=[
                Deliverable(title="one", description="the first"),
                Deliverable(title="two", description="the second"),
            ],
        ),
    )
    assert await route("product") == [
        ("architecture", {"title": "one", "description": "the first"}),
        ("architecture", {"title": "two", "description": "the second"}),
    ]


async def test_the_branch_key_reaches_the_architect_as_the_assignment(
    stage: Callable[..., None],
) -> None:
    """The payload is JSON by the time it arrives (04), and is read as such.

    It becomes the `## Your assignment` section of the prompt (19
    §Assembly): the one thing this branch is told that its siblings are
    not.
    """

    seen: list[str] = []

    class Recording(MockAgent):
        async def run(self, prompt: str = "") -> AgentResult:
            seen.append(prompt)
            return await super().run(prompt)

    stage("ArchitectAgent", agent=lambda: Recording(text="planned"))
    assert await route(
        "architecture", {"title": "one", "description": "the first"}
    ) == [("engineering", None)]
    assert seen == ["Deliverable for this branch: one. the first"]


async def test_an_architecture_task_moved_by_hand_carries_no_assignment(
    stage: Callable[..., None],
) -> None:
    """A payload slot bound to `None` is not an error (04 §Routing edge cases)."""

    assert feature_build._assignment(None) == ""
    stage("ArchitectAgent", text="planned from the log")
    assert await route("architecture", None) == [("engineering", None)]


@pytest.mark.parametrize(
    ("verdict", "target"),
    [("approve", "qa"), ("changes_requested", "engineering")],
)
async def test_the_review_routes_on_its_verdict(
    stage: Callable[..., None], verdict: str, target: str
) -> None:
    stage(
        "CodeReviewerAgent",
        output=ReviewDecision(verdict=verdict, feedback="line 4 is wrong"),  # type: ignore[arg-type]
    )
    assert await route("review") == [(target, None)]


@pytest.mark.parametrize(
    ("verdict", "target"),
    [("approve", "gate"), ("changes_requested", "engineering")],
)
async def test_qa_routes_on_its_verdict(
    stage: Callable[..., None], verdict: str, target: str
) -> None:
    stage("QAEngineerAgent", output=ReviewDecision(verdict=verdict))  # type: ignore[arg-type]
    assert await route("qa") == [(target, None)]


async def test_the_git_stage_ends_the_branch_with_what_it_reported(
    stage: Callable[..., None],
) -> None:
    """No edges, so the value is the branch's — and the run's — output."""

    stage("GitEngineerAgent", text="committed 4f21ac9")
    assert await route("git") == []
    assert await node("git").fn() == "committed 4f21ac9"


async def test_a_refused_agent_dead_letters_rather_than_retrying(
    stage: Callable[..., None],
) -> None:
    """A failed result is returned, not raised; the body decides (05).

    Every stage decides the same way, and `NonRetryable` is the decision:
    a refusal, a cancellation and a truncated turn do not improve when
    the same model is asked the same question again (04 §Failure classes).
    """

    class Refusing(MockAgent):
        async def run(self, prompt: str = "") -> AgentResult:
            return AgentResult(
                status="failed", error="I will not", stop_reason="refusal"
            )

    stage("SoftwareEngineerAgent", agent=Refusing)
    with pytest.raises(NonRetryable, match="I will not"):
        await route("engineering")


# --------------------------------------------------------------------------
# The gate: the one verdict no model gets a say in
# --------------------------------------------------------------------------


async def test_the_gate_sends_a_green_suite_to_git(
    monkeypatch: pytest.MonkeyPatch,
    store: Store,
    context: Callable[..., Any],
) -> None:
    ctx: TaskContext = await context(node="gate")
    monkeypatch.setattr(
        feature_build, "GATE_COMMAND", ("sh", "-c", "echo '3 passed'; exit 0")
    )
    with bind(ctx):
        assert await route("gate") == [("git", None)]
    written = await entries(store, ctx)
    assert [entry.author for entry in written] == [LogAuthor.engine]
    assert written[0].kind == LogKind.note
    assert written[0].text.startswith("test gate: PASS")
    assert "3 passed" in written[0].text


async def test_the_gate_sends_a_red_suite_back_with_its_output(
    monkeypatch: pytest.MonkeyPatch,
    store: Store,
    context: Callable[..., Any],
) -> None:
    ctx: TaskContext = await context(node="gate")
    monkeypatch.setattr(
        feature_build, "GATE_COMMAND", ("sh", "-c", "echo 'E   assert 1 == 2'; exit 1")
    )
    with bind(ctx):
        assert await route("gate") == [("engineering", None)]
    written = await entries(store, ctx)
    assert written[0].kind == LogKind.failure
    assert written[0].text.startswith("test gate: FAIL")
    assert "assert 1 == 2" in written[0].text


async def test_a_gate_command_that_is_not_installed_stops_the_run(
    monkeypatch: pytest.MonkeyPatch,
    context: Callable[..., Any],
) -> None:
    """Retrying spawns the same missing executable, so it does not retry."""

    ctx: TaskContext = await context(node="gate")
    monkeypatch.setattr(feature_build, "GATE_COMMAND", ("athanore-no-such-command",))
    with bind(ctx), pytest.raises(NonRetryable, match="athanore-no-such-command"):
        await route("gate")


def test_the_gate_output_is_capped() -> None:
    """A megabyte of pytest output is not a work-log entry."""

    assert feature_build.GATE_TAIL == 1500
    assert feature_build.GATE_COMMAND == ("uv", "run", "pytest", "-q")


# --------------------------------------------------------------------------
# Discovery and the programmatic host
# --------------------------------------------------------------------------


def test_the_distribution_advertises_the_workflow() -> None:
    """`athanore serve` needs to be told nothing (09 §Discovery)."""

    advertised = {
        entry.name: entry.value
        for entry in entry_points(group=GROUP)
        if entry.dist is not None and entry.dist.name == DISTRIBUTION
    }
    assert advertised == {"feature_build": "feature_build:wf"}


def test_athanore_serve_discovers_feature_build() -> None:
    """The exit condition of T074, asserted through the loader itself."""

    found = {workflow.name: workflow for workflow in discover()}
    assert found["feature_build"] is wf


def test_the_programmatic_host_registers_it_on_a_capacity_one_pool(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`examples/__main__.py` is 04 §Programmatic host's form, built."""

    for key in [name for name in os.environ if name.startswith("ATHANORE_")]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("ATHANORE_ROOT_PATH", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    spec = importlib.util.spec_from_file_location(
        "examples_main", ROOT / "examples" / "__main__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    server: Server = module.build()
    assert list(server.workflows) == ["feature_build"]
    assert server.engine.pools.snapshot() == {"local": {"capacity": 1, "in_flight": 0}}


# --------------------------------------------------------------------------
# The scenarios that run it with no model in the loop
# --------------------------------------------------------------------------


def test_every_agent_stage_ships_a_scenario() -> None:
    """13 §Running examples on the fake: one per node, plus the default.

    Named `<workflow>.<node>.json`, which is the fake's first lookup, so
    several examples' scenarios can share one directory without a `qa`
    scripting somebody else's.
    """

    assert {path.name for path in SCENARIOS.glob("*.json")} == {
        "default.json",
        *(f"feature_build.{name}.json" for name in STAGES),
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
    seat = STAGES[stage_name]
    # Every stage logs a deliverable: that is what the next one reads.
    assert scripted["log"].startswith(f"{stage_name}: ")
    model = seat.output_model
    if model is None:
        assert "submit" not in scripted, stage_name
    else:
        assert model.model_validate(scripted["submit"])
