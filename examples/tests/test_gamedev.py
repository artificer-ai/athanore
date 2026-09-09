"""`gamedev` on the v1 API: the graph, the prompts, the models, the plugin.

The MVP's game pipeline rewritten against `athanore` v1 (T075, D65), and
the worked example 09 §Declarations describes — so this file asserts two
things at once: a workflow that dispatches, and the plugin surface a
plugin author copies.

It asserts them the way `test_feature_build.py` does. **The bodies are
run**, with real :class:`~athanore.graph.EdgeRef` arguments, and what
comes back is handed to :func:`~athanore.engine.routing.interpret` — the
runner's own function rather than a restatement of it. **The agents are
replaced by name**, so :data:`STAGES` is checked against the bodies
instead of beside them: a body that instantiated a different class would
spawn a real `pi` and fail. **The scenarios are part of the example**,
validated against 13's vocabulary and each stage's ``output_model``.

The plugin half needs more than a body: a route reads a run's work log
and an action writes to it through the operator operations, so those
tests build a real store, a real engine with this workflow registered,
and resolve a real :class:`~athanore.plugins.context.PluginContext` over
them. Nothing there is a double — what the ``Words`` pane draws is what
the ``override`` action wrote.
"""

from __future__ import annotations

import importlib
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import gamedev
from athanore import AgentError, NonRetryable
from athanore.agents.base import Agent, AgentResult
from athanore.engine import Engine, Pool
from athanore.engine.context import TaskContext, bind
from athanore.engine.routing import interpret
from athanore.events.bus import EventBus
from athanore.events.names import EventName
from athanore.graph import EdgeRef, Graph, Node
from athanore.plugins.context import PluginHost
from athanore.plugins.decl import Action, PanelKind, Route, Slot
from athanore.plugins.discovery import discover
from athanore.plugins.registry import collect, validate
from athanore.settings import AthanoreSettings
from athanore.store.engine import make_engine
from athanore.store.rows import LogAuthor, LogKind, RunRow
from athanore.store.tables import metadata
from athanore.store.uow import Store
from athanore.testing import MockAgent, validate_scenario
from gamedev import (
    ArchitecturePlan,
    BuildStep,
    Deliverable,
    GameArchitectAgent,
    GameDesignerAgent,
    GamedevAgent,
    GameDirectorAgent,
    GameEngineerAgent,
    GameReviewerAgent,
    GameSpec,
    Override,
    PromptWriterAgent,
    QAEngineerAgent,
    ReviewDecision,
    wf,
)
from gamedev.plugin import (
    OVERRIDE_ACTION,
    WORD_COLUMNS,
    WORDS_PANEL,
    WORDS_ROUTE,
    overridden,
    word_entry,
)
from pi import PI_ACP_VERSION, PiSessionStats

#: One node, one seat. ``human_qa`` and ``publish`` are deliberately
#: absent: they run no agent, which is what makes one of them a question
#: for a person and the other a file that ships.
STAGES: dict[str, type[Agent]] = {
    "prompt": PromptWriterAgent,
    "design": GameDesignerAgent,
    "director": GameDirectorAgent,
    "architecture": GameArchitectAgent,
    "engineering": GameEngineerAgent,
    "review": GameReviewerAgent,
    "qa": QAEngineerAgent,
}

#: The pipeline, as the workflow's docstring draws it.
PIPELINE: dict[str, tuple[str, ...]] = {
    "prompt": ("design",),
    "design": ("director",),
    "director": ("architecture",),
    "architecture": ("engineering",),
    "engineering": ("review",),
    "review": ("engineering", "human_qa"),
    "human_qa": ("qa",),
    "qa": ("engineering", "publish"),
    "publish": (),
}

SCENARIOS = Path(gamedev.__file__).resolve().parent / "scenarios"

GRAPH: Graph = wf.finalize()

#: One game, as the director submits it and as the tail receives it.
GAME = {
    "title": "Neon Snake",
    "description": "A one-screen arcade snake.",
    "file_path": "output/neon-snake.html",
}

#: The architect's plan, as the payload carries it after coercion.
PLAN = {
    "summary": "two steps",
    "steps": [
        {
            "name": "scaffold",
            "charter": "skeleton and constants",
            "done_when": "the file parses",
        },
        {
            "name": "physics",
            "charter": "movement and wrap-around",
            "done_when": "step() advances the head",
        },
    ],
}


def node(name: str) -> Node:
    """One finalized node of the workflow."""

    return GRAPH.nodes[name]


async def route(name: str, payload: Any = None) -> list[tuple[str, Any]]:
    """Run node ``name``'s body and interpret what it returned."""

    one = node(name)
    slot = {one.payload_param: payload} if one.payload_param else {}
    value = await one.fn(*(EdgeRef(edge) for edge in one.edges), **slot)
    return [(step.target, step.payload) for step in interpret(one, value)]


class Recording(MockAgent):
    """A :class:`~athanore.testing.MockAgent` that keeps its prompts.

    Six of these stages are handed an assignment section, and what is in
    it is the only thing that distinguishes one branch — or one build
    step — from the next.
    """

    def __init__(self, seen: list[str], **scripted: Any) -> None:
        super().__init__(**scripted)
        self._seen = seen

    async def run(self, prompt: str = "") -> AgentResult:
        self._seen.append(prompt)
        return await super().run(prompt)


@pytest.fixture
def stage(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[str]]:
    """Replace one stage's agent class with a double, and record its prompts.

    By the name the body reaches for, so the substitution only works if
    the body really does run that seat. What comes back is the list the
    double appends each prompt to, which is what the assignment tests
    read.
    """

    def use(
        name: str, *, agent: Callable[[], Agent] | None = None, **scripted: Any
    ) -> list[str]:
        assert isinstance(getattr(gamedev, name, None), type), name
        seen: list[str] = []
        build = agent if agent is not None else (lambda: Recording(seen, **scripted))
        monkeypatch.setattr(gamedev, name, build, raising=True)
        return seen

    return use


# --------------------------------------------------------------------------
# The graph
# --------------------------------------------------------------------------


def test_the_graph_is_the_pipeline() -> None:
    """Signature is the graph: every edge is a parameter name (rule 1)."""

    assert GRAPH.name == "gamedev"
    assert GRAPH.start == "prompt"
    assert {name: one.edges for name, one in GRAPH.nodes.items()} == PIPELINE


def test_there_is_no_gate_and_no_git() -> None:
    """The browser is the test, and a game ships as a file (D65's port).

    `feature_build` ends on a deterministic gate and a commit. This one
    cannot: there are no unit tests for a game, so QA drives a real
    browser and `publish` names the file.
    """

    assert "gate" not in GRAPH.nodes
    assert "git" not in GRAPH.nodes
    terminal = sorted(name for name, one in GRAPH.nodes.items() if not one.edges)
    assert terminal == ["publish"]


def test_the_verdicts_loop_back_to_engineering() -> None:
    """Review and QA each hold the edge that sends the build back."""

    for name in ("review", "qa"):
        assert "engineering" in node(name).edges, name
    assert node("engineering").edges == ("review",)
    # The playtest has no verdict to route on: whatever the operator
    # says goes to QA, which weighs it. A person is not a gate.
    assert node("human_qa").edges == ("qa",)


def test_the_fan_out_is_the_only_plain_payload() -> None:
    """One key per branch out of the director; a composite down the tail."""

    slots = {name: one.payload_param for name, one in GRAPH.nodes.items()}
    assert slots == {
        "prompt": None,
        "design": None,
        "director": None,
        "architecture": "deliverable",
        "engineering": "branch",
        "review": "branch",
        "human_qa": "branch",
        "qa": "branch",
        "publish": "branch",
    }
    # Keyword-only, so neither can be mistaken for an edge (04 §Signature
    # parsing).
    assert "deliverable" not in node("architecture").edges
    assert "branch" not in node("engineering").edges


def test_every_node_declares_its_retries_and_its_timeout() -> None:
    """The metadata seam, used: no body counts its own attempts (rule 3)."""

    for name, one in GRAPH.nodes.items():
        assert one.retries is not None, name
        assert one.timeout is not None and one.timeout > 0, name
    # Engineering is the long one: it runs a session per build step.
    assert node("engineering").timeout == max(
        one.timeout or 0 for one in GRAPH.nodes.values()
    )


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
    """`AGENTS.md`: agent prompts are inlined text on agent classes."""

    seat = STAGES[name]
    prompt = vars(seat).get("system_prompt")
    assert isinstance(prompt, str) and prompt.strip(), name
    assert prompt.lstrip().startswith("# "), name
    # It names the pipeline it belongs to, which is how a model reading
    # one stage knows what happens either side of it.
    assert "prompt → design → director" in prompt, name
    assert "→ review → human_qa → qa → publish" in prompt, name


@pytest.mark.parametrize("name", sorted(STAGES))
def test_every_prompt_states_the_pipeline_constraints(name: str) -> None:
    """One game, one file: the rule the whole example exists to hold."""

    prompt = STAGES[name].system_prompt or ""
    assert "single-file HTML games" in prompt, name


@pytest.mark.parametrize("name", sorted(STAGES))
def test_no_stage_loads_its_prompt_from_a_file(name: str) -> None:
    """`template=` is gone (05 §Agent classes) and nothing replaced it."""

    module = importlib.import_module(STAGES[name].__module__)
    assert module.__file__ is not None
    source = Path(module.__file__).read_text(encoding="utf-8")
    for forbidden in ("open(", "read_text", "Template", "loads(", "importlib"):
        assert forbidden not in source, f"{name} reaches for {forbidden}"


# --------------------------------------------------------------------------
# The models
# --------------------------------------------------------------------------


def test_an_output_model_is_declared_wherever_the_graph_routes_on_one() -> None:
    """Rule 2 with a shape: a decision the engine reads is a model."""

    declared = {name: STAGES[name].output_model for name in STAGES}
    assert declared == {
        "prompt": None,
        "design": None,
        "director": GameSpec,
        "architecture": ArchitecturePlan,
        "engineering": None,
        "review": ReviewDecision,
        "qa": ReviewDecision,
    }
    branching = {name for name, one in GRAPH.nodes.items() if len(one.edges) > 1}
    assert branching == {"review", "qa"}
    assert all(STAGES[name].output_model is not None for name in branching)


def test_a_spec_with_no_games_is_refused() -> None:
    """The fan-out cannot be empty: `return []` would end the run silently."""

    with pytest.raises(ValidationError):
        GameSpec(summary="none", deliverables=[])


def test_a_game_that_is_not_one_file_under_output_is_refused() -> None:
    """The pipeline's one hard constraint, machine-checked at the split.

    As a pattern it is a 422 the director repairs inside its own session
    (19 §Repair turn); as prose in a prompt it is a path nobody notices
    until a game is written somewhere else.
    """

    assert Deliverable(**GAME).file_path == "output/neon-snake.html"
    for bad in (
        "neon-snake.html",
        "output/neon snake.html",
        "output/NeonSnake.html",
        "output/neon-snake.htm",
        "games/neon-snake.html",
        "output/neon-snake.html.bak",
    ):
        with pytest.raises(ValidationError):
            Deliverable(title="t", description="d", file_path=bad)


def test_a_plan_with_no_steps_is_refused() -> None:
    """Engineering executes the list; an empty one builds nothing."""

    with pytest.raises(ValidationError):
        ArchitecturePlan(summary="none", steps=[])
    plan = ArchitecturePlan(
        summary="one",
        steps=[BuildStep(name="scaffold", charter="c", done_when="d")],
    )
    assert len(plan.steps) == 1


def test_a_verdict_is_one_of_two_words() -> None:
    """The node branches on it, so it may not be free text."""

    assert ReviewDecision(verdict="approve").feedback == ""
    with pytest.raises(ValidationError):
        ReviewDecision(verdict="looks fun")  # type: ignore[arg-type]


def test_an_override_needs_a_word_and_may_omit_its_reason() -> None:
    """The action's model is the form the SPA renders (09)."""

    assert Override(word="Viper").reason == ""
    with pytest.raises(ValidationError):
        Override(word="")


def test_the_form_reads_as_prose_in_a_browser() -> None:
    """The model's docstring and descriptions are shown above the form.

    The SPA draws the JSON Schema the manifest carries, and pydantic
    takes the ``description`` of an object from its docstring — so an
    action model documented in reStructuredText shows an operator stray
    backticks. Every string an operator reads is checked here rather than
    left to whoever next opens the overlay.
    """

    schema = Override.model_json_schema()
    prose = [schema["description"]] + [
        field["description"] for field in schema["properties"].values()
    ]
    for line in prose:
        assert line and line[0].isupper() and line.rstrip().endswith("."), line
        for markup in ("``", ":class:", ":func:", ":mod:", ":attr:", "§"):
            assert markup not in line, f"{markup} reaches the form: {line!r}"


# --------------------------------------------------------------------------
# The seat
# --------------------------------------------------------------------------


def test_every_stage_sits_in_the_one_pinned_pi_seat() -> None:
    """05 §User-land adapters: the vendor knowledge is in `examples/`."""

    assert GamedevAgent.command == ["npx", "-y", f"pi-acp@{PI_ACP_VERSION}"]
    assert isinstance(GamedevAgent.stats_provider, PiSessionStats)
    assert GamedevAgent.tooling == "native"
    assert GamedevAgent.model == gamedev.MODEL
    # Reasoning off, on every seat: a stage of this pipeline writes a
    # whole game into one file, so the output budget is the scarce thing.
    assert GamedevAgent.thinking == "off"
    for name, seat in STAGES.items():
        assert issubclass(seat, GamedevAgent), name
        assert seat.model == gamedev.MODEL, name
        assert seat.thinking == "off", name
        declared = {key for key in vars(seat) if not key.startswith("__")}
        assert declared <= {"system_prompt", "output_model"}, name


# --------------------------------------------------------------------------
# The routing (the bodies, run)
# --------------------------------------------------------------------------


async def test_intake_and_design_hand_straight_on(
    stage: Callable[..., list[str]],
) -> None:
    stage("PromptWriterAgent", text="brief")
    assert await route("prompt") == [("design", None)]
    stage("GameDesignerAgent", text="design doc")
    assert await route("design") == [("director", None)]


async def test_the_director_fans_out_one_branch_per_game(
    stage: Callable[..., list[str]],
    store: Store,
    context: Callable[..., Any],
) -> None:
    """Called refs carry the payload that tells the branches apart."""

    ctx: TaskContext = await context(node="director")
    stage(
        "GameDirectorAgent",
        output=GameSpec(
            summary="two games",
            deliverables=[
                Deliverable(**GAME),
                Deliverable(
                    title="Breakout",
                    description="bricks",
                    file_path="output/breakout.html",
                ),
            ],
        ),
    )
    with bind(ctx):
        assert await route("director") == [
            ("architecture", GAME),
            (
                "architecture",
                {
                    "title": "Breakout",
                    "description": "bricks",
                    "file_path": "output/breakout.html",
                },
            ),
        ]
    # And the names it chose are in the work log as data, which is what
    # the `Words` pane reads.
    written = await entries(store, ctx.run_id)
    assert [entry.text for entry in written] == [
        "word: Neon Snake → output/neon-snake.html",
        "word: Breakout → output/breakout.html",
    ]
    assert {entry.author for entry in written} == {LogAuthor.engine}


async def test_the_architect_is_told_its_game_and_hands_on_a_plan(
    stage: Callable[..., list[str]],
) -> None:
    """The payload becomes the `## Your assignment` section (19 §Assembly)."""

    seen = stage("GameArchitectAgent", output=ArchitecturePlan.model_validate(PLAN))
    steps = await route("architecture", GAME)
    # The composite reaches the tail as JSON: `interpret` coerces every
    # payload with `jsonable()` (04 §Routing interpretation), so what
    # engineering reads is the plan as data and not as a model.
    assert steps == [("engineering", {"deliverable": GAME, "plan": PLAN})]
    assert seen == [
        "Deliverable for this branch: Neon Snake.\n"
        "Target file: output/neon-snake.html.\n"
        "A one-screen arcade snake."
    ]


async def test_an_architecture_task_moved_by_hand_carries_no_assignment(
    stage: Callable[..., list[str]],
) -> None:
    """A payload slot bound to `None` is not an error (04 §Routing edge cases)."""

    assert gamedev._assignment(None) == ""
    seen = stage("GameArchitectAgent", output=ArchitecturePlan.model_validate(PLAN))
    assert await route("architecture", None) == [
        ("engineering", {"deliverable": None, "plan": PLAN})
    ]
    assert seen == [""]


async def test_engineering_runs_the_build_steps_serially(
    stage: Callable[..., list[str]],
) -> None:
    """One focused session per step, in order, each told which it is."""

    seen = stage("GameEngineerAgent", text="wrote the section")
    branch = {"deliverable": GAME, "plan": PLAN}
    assert await route("engineering", branch) == [("review", branch)]
    assert len(seen) == 2
    assert "SCAFFOLD step: scaffold (1/2)" in seen[0]
    assert "skeleton and constants" in seen[0]
    assert "FINAL build step" not in seen[0]
    assert "Build step 2/2" in seen[1]
    assert "This is the FINAL build step." in seen[1]
    assert "movement and wrap-around" in seen[1]
    # Every step is told which game it is building, not only the first.
    assert all("output/neon-snake.html" in prompt for prompt in seen)


async def test_a_failed_build_step_is_retryable_rather_than_a_dead_letter(
    stage: Callable[..., list[str]],
) -> None:
    """The opposite of every other stage here, and deliberately so.

    The usual failure is a turn truncated at the model's output limit,
    which is exactly the case a second attempt can win — so this one
    raises into rule 3's retry budget rather than dead-lettering.
    """

    class Truncating(MockAgent):
        async def run(self, prompt: str = "") -> AgentResult:
            if "physics" in prompt:
                return AgentResult(status="failed", error="max output tokens")
            return AgentResult()

    stage("GameEngineerAgent", agent=Truncating)
    with pytest.raises(AgentError, match=r"step 2/2 \(physics\).*max output"):
        await route("engineering", {"deliverable": GAME, "plan": PLAN})


async def test_a_loop_back_without_a_plan_is_one_targeted_fix(
    stage: Callable[..., list[str]],
) -> None:
    """Review and QA drop the plan; the absence of it is the signal."""

    seen = stage("GameEngineerAgent", text="fixed it")
    branch = {"deliverable": GAME}
    assert await route("engineering", branch) == [("review", branch)]
    assert len(seen) == 1
    assert "Deliverable for this branch: Neon Snake." in seen[0]
    assert "Build step" not in seen[0]


@pytest.mark.parametrize(
    ("verdict", "target"),
    [("approve", "human_qa"), ("changes_requested", "engineering")],
)
async def test_the_review_routes_on_its_verdict(
    stage: Callable[..., list[str]], verdict: str, target: str
) -> None:
    stage(
        "GameReviewerAgent",
        output=ReviewDecision(verdict=verdict, feedback="the delta is not clamped"),  # type: ignore[arg-type]
    )
    branch = {"deliverable": GAME, "plan": PLAN}
    steps = await route("review", branch)
    if target == "human_qa":
        # Approved: the whole branch travels on, plan and all.
        assert steps == [("human_qa", branch)]
    else:
        # Sent back: the game without the plan, which engineering reads
        # as one targeted fix.
        assert steps == [("engineering", {"deliverable": GAME})]


async def test_the_playtest_asks_the_operator_and_threads_the_reply(
    monkeypatch: pytest.MonkeyPatch,
    store: Store,
    context: Callable[..., Any],
) -> None:
    """`human_input` is the node's only work, and the answer is QA's input."""

    asked: list[str] = []

    async def answer(prompt: str, **kwargs: Any) -> str:
        asked.append(prompt)
        return "the pellets are invisible on the grid"

    monkeypatch.setattr(gamedev, "human_input", answer)
    ctx: TaskContext = await context(node="human_qa")
    branch = {"deliverable": GAME}
    with bind(ctx):
        steps = await route("human_qa", branch)
    assert steps == [
        (
            "qa",
            {
                "deliverable": GAME,
                "human_feedback": "the pellets are invisible on the grid",
            },
        )
    ]
    assert asked == [
        gamedev.PLAYTEST_QUESTION.format(file_path="output/neon-snake.html")
    ]
    # The report is in the work log too, filed to the operator: the run
    # is the record, not the transition.
    written = await entries(store, ctx.run_id)
    assert [(entry.author, entry.text) for entry in written] == [
        (LogAuthor.user, "playtest report: the pellets are invisible on the grid")
    ]


async def test_qa_is_handed_the_playtest_report_as_part_of_its_verdict(
    stage: Callable[..., list[str]],
) -> None:
    """A person's report is evidence QA weighs, not advice it may skip."""

    seen = stage("QAEngineerAgent", output=ReviewDecision(verdict="approve"))
    branch = {"deliverable": GAME, "human_feedback": "the pellets are invisible"}
    assert await route("qa", branch) == [("publish", branch)]
    assert "Operator playtest report" in seen[0]
    assert "the pellets are invisible" in seen[0]


async def test_qa_without_a_playtest_report_says_nothing_about_one(
    stage: Callable[..., list[str]],
) -> None:
    """A task moved onto `qa` by hand skipped the question; that is not an error."""

    seen = stage("QAEngineerAgent", output=ReviewDecision(verdict="approve"))
    assert await route("qa", {"deliverable": GAME}) == [
        ("publish", {"deliverable": GAME})
    ]
    assert "Operator playtest report" not in seen[0]


async def test_qa_sends_a_failed_game_back_without_the_plan(
    stage: Callable[..., list[str]],
) -> None:
    stage(
        "QAEngineerAgent",
        output=ReviewDecision(verdict="changes_requested", feedback="dead controls"),
    )
    assert await route("qa", {"deliverable": GAME, "plan": PLAN}) == [
        ("engineering", {"deliverable": GAME})
    ]


async def test_publish_ends_the_branch_with_the_file_it_shipped(
    store: Store, context: Callable[..., Any]
) -> None:
    """No edges, so the value is the branch's — and the run's — output."""

    ctx: TaskContext = await context(node="publish")
    with bind(ctx):
        assert await route("publish", {"deliverable": GAME}) == []
        shipped = await node("publish").fn(branch={"deliverable": GAME})
    assert shipped == GAME["file_path"]
    written = await entries(store, ctx.run_id)
    assert written[0].kind == LogKind.deliverable
    assert written[0].text.startswith("game shipped: output/neon-snake.html")


async def test_a_refused_agent_dead_letters_rather_than_retrying(
    stage: Callable[..., list[str]],
) -> None:
    """A failed result is returned, not raised; the body decides (05)."""

    class Refusing(MockAgent):
        async def run(self, prompt: str = "") -> AgentResult:
            return AgentResult(
                status="failed", error="I will not", stop_reason="refusal"
            )

    stage("PromptWriterAgent", agent=Refusing)
    with pytest.raises(NonRetryable, match="I will not"):
        await route("prompt")


async def test_a_director_that_submitted_nothing_dead_letters(
    stage: Callable[..., list[str]],
) -> None:
    """ "The agent submitted nothing" is a dead letter, not an AttributeError."""

    stage("GameDirectorAgent", text="I wrote it in prose instead")
    with pytest.raises(NonRetryable, match="expected a GameSpec submission"):
        await route("director")


# --------------------------------------------------------------------------
# The plugin surface (09 §Declarations, on a real run)
# --------------------------------------------------------------------------


@pytest.fixture
async def plugin(tmp_path: Path) -> AsyncIterator[tuple[PluginHost, Store, RunRow]]:
    """A store, an engine with `gamedev` registered, and one run of it.

    Real collaborators rather than doubles: the route reads the work log
    out of the store and the action writes to it through the engine's
    operations, so a fixture that faked either would be asserting
    nothing about the declarations.
    """

    bus = EventBus()
    sa_engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'athanore.db'}")
    async with sa_engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    store = Store(sa_engine, bus)
    settings = AthanoreSettings(root_path=tmp_path, workers=1)
    engine = Engine(settings, store, bus)
    spec = collect(wf)
    validate(spec, GRAPH)
    engine.register(GRAPH, Pool("local", 1))
    async with store.uow() as uow:
        run = await uow.runs.insert("gamedev", "Neon snake")
        await uow.tasks.enqueue(run.id, "director", None, priority=0, explicit=False)
    try:
        yield PluginHost(store, engine), store, run
    finally:
        await sa_engine.dispose()


def declaration(kind: str, name: str) -> Any:
    """One declaration of this workflow, by name, off the collected spec."""

    spec = collect(wf)
    found = [
        one
        for one in getattr(spec, kind)
        if (one.path if isinstance(one, Route) else one.name) == name
    ]
    assert len(found) == 1, f"{kind} {name}"
    return found[0]


def test_the_showcase_declares_the_three_things_09_shows() -> None:
    """A route, an action whose model is its form, and a table pane."""

    spec = collect(wf)
    validate(spec, GRAPH)
    assert [one.path for one in spec.routes] == [WORDS_ROUTE]
    assert [one.name for one in spec.actions] == [OVERRIDE_ACTION]
    assert [one.name for one in spec.panels] == [WORDS_PANEL]

    action: Action = spec.actions[0]
    assert action.scope is Slot.run
    assert action.confirm is True
    assert action.title == "Override the game's name"
    # The model *is* the form: it is taken off the handler's own `input`
    # annotation, not declared twice.
    assert action.model is Override

    panel = spec.panels[0]
    assert panel.slot is Slot.run
    assert panel.kind is PanelKind.table
    assert panel.source is spec.routes[0].fn
    # What makes it stale is what the action emits, which is the seam
    # closing on itself.
    assert panel.refresh_on == (EventName.log_appended.value,)


async def test_the_words_pane_draws_the_names_the_director_chose(
    plugin: tuple[PluginHost, Store, RunRow],
) -> None:
    """The route's shape is 09's `table`: `{columns, rows}`."""

    host, store, run = plugin
    async with store.uow() as uow:
        await uow.log.append(
            run_id=run.id,
            node="director",
            author=LogAuthor.engine,
            text=word_entry("Neon Snake", file_path="output/neon-snake.html"),
        )
        await uow.log.append(
            run_id=run.id,
            node="design",
            author=LogAuthor.agent,
            text="design: a snake on a neon grid",
        )
    ctx = await host.context(workflow="gamedev", run_id=run.id)
    data = await declaration("routes", WORDS_ROUTE).fn(ctx)
    assert data["columns"] == WORD_COLUMNS
    # Only the lines that are names: the rest of the work log is prose.
    assert data["rows"] == [
        {
            "word": "Neon Snake",
            "file": "output/neon-snake.html",
            "author": "engine",
        }
    ]


async def test_the_words_pane_caps_from_the_end(
    plugin: tuple[PluginHost, Store, RunRow],
) -> None:
    """`limit` is an ordinary FastAPI parameter, and the recent names win."""

    host, store, run = plugin
    async with store.uow() as uow:
        for index in range(4):
            await uow.log.append(
                run_id=run.id,
                node="director",
                author=LogAuthor.engine,
                text=word_entry(f"Game {index}"),
            )
    ctx = await host.context(workflow="gamedev", run_id=run.id)
    words = declaration("routes", WORDS_ROUTE).fn
    assert [row["word"] for row in (await words(ctx, limit=2))["rows"]] == [
        "Game 2",
        "Game 3",
    ]
    assert (await words(ctx, limit=0))["rows"] == []
    # A name with no file omits the key rather than sending "" — unknown
    # is absent (01 §Real data only).
    assert "file" not in (await words(ctx))["rows"][0]


async def test_the_override_action_writes_the_name_and_announces_it(
    plugin: tuple[PluginHost, Store, RunRow],
) -> None:
    """It writes through `ops`, which is what a `run`-scoped action has.

    The run-scoped *services* belong to an attempt (09 §Context and
    scopes), so a run in scope with no task cannot reach the work log
    through them; `ops.append_log` takes the run id explicitly. The entry
    lands as the operator's, and the event is this workflow's own
    namespace.
    """

    host, store, run = plugin
    ctx = await host.context(workflow="gamedev", run_id=run.id)
    result = await declaration("actions", OVERRIDE_ACTION).fn(
        ctx, Override(word="Viper", reason="Neon Snake is taken")
    )
    assert result["word"] == "Viper"

    written = await entries(store, run.id)
    assert [(entry.author, entry.text) for entry in written] == [
        (LogAuthor.user, "word: Viper — Neon Snake is taken")
    ]
    # And the pane the operator is looking at draws it, without the
    # action telling it to: the `log.appended` it emitted is what
    # `refresh_on` names.
    data = await declaration("routes", WORDS_ROUTE).fn(ctx)
    assert data["rows"] == [
        {"word": "Viper", "why": "Neon Snake is taken", "author": "user"}
    ]

    async with store.reader() as reader:
        events = await reader.events.list_for_run(run.id)
    names = [event.name for event in events]
    assert overridden("gamedev") in names
    assert EventName.log_appended.value in names


async def test_an_override_with_no_reason_is_still_a_name(
    plugin: tuple[PluginHost, Store, RunRow],
) -> None:
    """`reason` defaults to empty, and an empty one adds no parenthesis."""

    host, store, run = plugin
    ctx = await host.context(workflow="gamedev", run_id=run.id)
    await declaration("actions", OVERRIDE_ACTION).fn(ctx, Override(word="Viper"))
    written = await entries(store, run.id)
    assert written[0].text == "word: Viper"


async def test_a_plugin_cannot_be_pointed_at_another_workflows_run(
    plugin: tuple[PluginHost, Store, RunRow],
) -> None:
    """Scope follows ownership, and the refusal is a 404 (09)."""

    from athanore.plugins.decl import PluginError

    host, store, _ = plugin
    async with store.uow() as uow:
        other = await uow.runs.insert("feature_build", "not ours")
    with pytest.raises(PluginError) as raised:
        await host.context(workflow="gamedev", run_id=other.id)
    assert raised.value.status == 404


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


def test_athanore_serve_discovers_gamedev() -> None:
    """`athanore serve` needs to be told nothing (09 §Discovery)."""

    found = {workflow.name: workflow for workflow in discover()}
    assert found["gamedev"] is wf


# --------------------------------------------------------------------------
# The scenarios that run it with no model in the loop
# --------------------------------------------------------------------------


def test_every_agent_stage_ships_a_scenario() -> None:
    """13 §Running examples on the fake: one per agent node, plus the default.

    `human_qa` and `publish` have none and cannot have one: they run no
    agent. A scripted run therefore stops at the playtest question until
    somebody answers it, which is the pipeline working rather than the
    fixture failing.
    """

    assert {path.name for path in SCENARIOS.glob("*.json")} == {
        "default.json",
        *(f"gamedev.{name}.json" for name in STAGES),
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
    assert scripted["log"].startswith(f"{stage_name}: ")
    model = seat.output_model
    if model is None:
        assert "submit" not in scripted, stage_name
    else:
        assert model.model_validate(scripted["submit"])


def test_the_scripted_run_builds_a_game_the_pipeline_would_accept() -> None:
    """The director's scenario names a file the branch can really write.

    A scenario that submitted `games/x.html` would be repaired forever
    rather than fanning out, so the pattern is checked here as well as at
    the model — this is the fixture that has to satisfy it.
    """

    scripted = json.loads(
        (SCENARIOS / "gamedev.director.json").read_text(encoding="utf-8")
    )
    spec = GameSpec.model_validate(scripted["submit"])
    assert [one.file_path for one in spec.deliverables] == ["output/neon-snake.html"]
    plan = json.loads(
        (SCENARIOS / "gamedev.architecture.json").read_text(encoding="utf-8")
    )
    # The first step scaffolds, which is what the architect's prompt
    # promises engineering and what the engineering body assumes.
    assert ArchitecturePlan.model_validate(plan["submit"]).steps[0].name == "scaffold"


async def entries(store: Store, run_id: str) -> list[Any]:
    """The work-log entries of a run, oldest first, read back out of the store."""

    async with store.uow() as uow:
        return await uow.log.list(run_id)
