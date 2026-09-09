"""The reference plugin: one workflow that uses every declaration (T073).

09 is the specification and this module is its acceptance test's subject.
It declares **one of everything the plugin vocabulary offers** — a route,
an action whose model nests, a panel of every ``kind`` in every ``slot``
and both ``placement``s, a ``node``-slot panel, an ``on`` handler, and an
``assets`` directory — so that ``tests/plugins/test_suite.py`` can assert
the whole surface against one manifest. If a declaration cannot be
expressed here, the vocabulary has a hole.

It is also the example a plugin author reads, so nothing in it is a stub.
Every route answers with the shape 09 §Panel kinds promises for the kind
that sources it, read out of the store through ``ctx.services``; the
action validates a nested model, writes the work log and publishes a
``plugin.*`` event; the ``on`` handler reads the run back out of the
store, which is what "after commit" means from inside one.

**Why several routes.** 09's kind table gives each kind a data shape, and
a route returns one shape. A fixture that declared one panel per kind and
pointed them all at a single route would be describing a server that does
not exist — so there is one route per data kind, plus the ``POST`` the
custom element calls, which is where ``methods=`` earns its place.

The graph is two nodes because the ``node`` slot needs a node that is not
the one the run starts in: ``judge`` is idle while ``play`` is in flight
and live once it has produced output, which is the liveness flip 08
§Graph semantics computes and the suite asserts.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from athanore.events.model import Event
from athanore.plugins.context import NO_NODE, PluginContext
from athanore.plugins.decl import PluginError
from athanore.store.rows import ChunkKind, EventRow, LogEntryRow
from athanore.workflow import Workflow

__all__ = [
    "ASSETS",
    "ELEMENT",
    "NODE_COLUMNS",
    "SECRET",
    "WORD_COLUMNS",
    "WORKFLOW",
    "Guess",
    "Override",
    "Reason",
    "fixture_workflow",
    "overridden",
    "recorded",
    "rules_text",
]

#: The workflow's name, and therefore its route prefix, its asset prefix
#: and its ``plugin.*`` namespace. 09's running example is a game, and so
#: is this.
WORKFLOW = "gamedev"

#: The ``assets=`` this workflow declares, relative to *this module* —
#: which is what 09 §Escape hatch resolves it against.
ASSETS = "./assets"

#: The custom element ``assets/playfield.js`` defines.
ELEMENT = "gd-playfield"

#: The word a run plays with, and the length its score is.
SECRET = "athanor"

#: The columns of the ``table`` panel, with the column hints of 09.
WORD_COLUMNS: list[dict[str, str]] = [
    {"key": "node", "label": "NODE", "kind": "text"},
    {"key": "word", "label": "WORD", "kind": "text"},
    {"key": "author", "label": "BY", "kind": "text"},
]

#: The columns of the ``dashboard`` panel's table.
NODE_COLUMNS: list[dict[str, str]] = [
    {"key": "node", "label": "NODE", "kind": "text"},
    {"key": "status", "label": "STATUS", "kind": "status"},
]


def rules_text(workflow: str = WORKFLOW) -> str:
    """The prose the ``markdown`` panel draws.

    A ``workflow``-slot pane is the library's detail side, so what
    belongs on it is what the workflow *is* — which is why it is the one
    pane that needs no run resolved.
    """

    return (
        f"# {workflow}\n"
        "\n"
        "`play` picks the secret word, `judge` scores it. The score is "
        f"the word's length, so `{SECRET}` is worth {len(SECRET)}.\n"
    )


def overridden(workflow: str = WORKFLOW) -> str:
    """The event the ``override`` action publishes.

    Derived from the workflow's name rather than written out, because a
    plugin may publish only in **its own** namespace (18 §Plugins) and
    this workflow is built under whatever name it was asked for.
    """

    return f"plugin.{workflow}.overridden"


def recorded(workflow: str = WORKFLOW) -> str:
    """The event the ``run.completed`` handler publishes."""

    return f"plugin.{workflow}.recorded"


class Reason(BaseModel):
    """Why an operator overrode the word — the nested half of the form."""

    text: str = Field(min_length=1, description="What justifies the override.")
    weight: int = Field(default=1, ge=1, le=5, description="How strongly.")


class Override(BaseModel):
    """The action's input, and therefore the form the SPA renders.

    Nested on purpose: 17 §T073 asks for a nested model because a flat
    one proves nothing about the JSON Schema the manifest carries — a
    ``$ref`` into ``$defs`` is what a form renderer actually has to
    handle.
    """

    word: str = Field(min_length=1, description="The word to play instead.")
    reason: Reason = Field(description="Why.")


class Guess(BaseModel):
    """What the custom element posts to ``POST /guess``."""

    word: str = Field(min_length=1, description="The player's guess.")


def fixture_workflow(name: str = WORKFLOW) -> Workflow:
    """Build the fixture workflow, fresh.

    A factory rather than a module-level singleton so that each test gets
    a workflow of its own: ``finalize()`` caches, and a graph registered
    on one test's engine has no business being on the next one's.
    ``name`` is a parameter so a suite can stand two of these up and ask
    what one workflow can see of another's runs.
    """

    wf = Workflow(name, assets=ASSETS)

    # -- the graph the plugin surface hangs on -----------------------------

    @wf.node(start=True, label="Play")
    async def play(judge):
        """Pick the word this run is about."""

        return judge(SECRET)

    @wf.node(label="Judge")
    async def judge(*, word):
        """Score the word the round produced."""

        return {"word": word, "score": len(word)}

    # -- routes: one per data kind, plus the element's own -----------------

    @wf.route("/rules")
    async def rules(ctx: PluginContext) -> str:
        """What this workflow is, as prose.

        The ``markdown`` shape is a string, and this route needs nothing
        resolved: a ``workflow``-slot pane is shown beside the workflow
        in the library, where there is no run at all.
        """

        return rules_text(name)

    @wf.route("/round")
    async def round_(ctx: PluginContext) -> dict[str, Any]:
        """This run's word and score, as a description list."""

        run = await ctx.services.run.get()
        output = run.output if isinstance(run.output, dict) else {}
        entry: dict[str, Any] = {"Run": run.title, "Status": run.status.value}
        if "word" in output:
            entry["Word"] = output["word"]
        if "score" in output:
            entry["Score"] = output["score"]
        return entry

    @wf.route("/words")
    async def words(ctx: PluginContext, limit: int = 50) -> dict[str, Any]:
        """Every word this run has written down, most recent last.

        ``limit`` is an ordinary FastAPI parameter — parsed, defaulted
        and documented without this workflow doing anything about it,
        which is 09's "any other parameter follows normal FastAPI
        rules".
        """

        entries = await ctx.services.run.log_entries()
        rows = [_word_row(entry) for entry in entries if entry.text.startswith("word:")]
        return {"columns": WORD_COLUMNS, "rows": rows[-limit:] if limit > 0 else []}

    @wf.route("/history")
    async def history(ctx: PluginContext) -> list[dict[str, Any]]:
        """This run's stored events, as a log stream."""

        events = await ctx.services.run.events()
        return [_log_row(event) for event in events]

    @wf.route("/scores")
    async def scores(ctx: PluginContext) -> dict[str, Any]:
        """One point per finished attempt: how long each stage took."""

        _, tasks, _ = await ctx.services.run.detail()
        points = [
            [task.id, round((task.finished - task.started).total_seconds(), 6)]
            for task in tasks
            if task.started is not None and task.finished is not None
        ]
        return {"series": [{"name": "duration", "points": points}], "kind": "bar"}

    @wf.route("/summary")
    async def summary(ctx: PluginContext) -> dict[str, Any]:
        """The run's tiles and its node table.

        Nothing is zero-filled (01 §Real data only): a metric no attempt
        reported is absent rather than claiming zero, which is why
        ``TOKENS`` comes and goes with the stats entries.
        """

        run, tasks, stats = await ctx.services.run.detail()
        metrics: list[dict[str, Any]] = [{"label": "ATTEMPTS", "value": len(tasks)}]
        if stats.total_tokens is not None:
            metrics.append({"label": "TOKENS", "value": stats.total_tokens})
        body: dict[str, Any] = {
            "metrics": metrics,
            "table": {
                "columns": NODE_COLUMNS,
                "rows": [
                    {"node": task.node, "status": task.status.value} for task in tasks
                ],
            },
        }
        if run.description:
            body["note"] = run.description
        return body

    @wf.route("/verdict")
    async def verdict(ctx: PluginContext) -> dict[str, Any]:
        """What the node in scope produced, as a description list.

        The ``node``-slot pane's data. A route reads its node off the
        ``node`` query parameter — or off the task, when one was named —
        and refuses when there is none, because a pane about a node that
        was not named has nothing to draw.
        """

        if ctx.node is None:
            raise PluginError(400, NO_NODE)
        _, tasks, _ = await ctx.services.run.detail()
        attempts = [task for task in tasks if task.node == ctx.node]
        entry: dict[str, Any] = {"Node": ctx.node, "Attempts": len(attempts)}
        if attempts:
            last = attempts[-1]
            entry["Status"] = last.status.value
            if last.result is not None:
                entry["Result"] = last.result
        return entry

    @wf.route("/guess", methods="POST")
    async def guess(ctx: PluginContext, input: Guess) -> dict[str, Any]:
        """Record a guess the custom element made, on the attempt in scope.

        The one route that is not a panel source: ``window.athanore.fetch``
        is how an element reaches its own workflow's API, and a plugin
        that only ever answered ``GET`` would leave ``methods=`` untested.
        The guess goes to the attempt's transcript as a ``notice``, which
        is what that chunk kind is for — a line the host wrote rather
        than the agent.
        """

        seq = await ctx.services.stream.append(ChunkKind.notice, f"guess: {input.word}")
        return {"seq": seq, "correct": input.word == SECRET}

    # -- one action, whose model is its form -------------------------------

    @wf.action(
        "override",
        title="Override the secret word",
        scope="task",
        confirm=True,
    )
    async def override(ctx: PluginContext, input: Override) -> dict[str, Any]:
        """Replace the word, and say in the work log who did it and why.

        Task-scoped, so the entry lands on the attempt the operator was
        looking at. The event it publishes is this workflow's own
        namespace — the only namespace a plugin may publish in (18
        §Plugins) — and it is emitted in a transaction of its own, after
        the log entry's, so a subscriber that sees it can already read
        the entry.
        """

        entry = await ctx.services.log.append(f"word: {input.word}", author="user")
        await ctx.services.events.publish(
            overridden(name),
            {
                "word": input.word,
                "reason": input.reason.text,
                "weight": input.reason.weight,
            },
        )
        return {"entry_id": entry.id, "word": input.word, "node": ctx.node}

    # -- one subscription --------------------------------------------------

    @wf.on("run.completed")
    async def announce(ctx: PluginContext, event: Event) -> None:
        """Publish what the store says about the run this event announced.

        The whole point of reading the run back rather than trusting the
        payload: an ``on`` handler runs after the transaction that
        emitted the event has committed, so the status and the output
        this publishes are the durable ones. A handler that fired inside
        the transaction would read a run that is still ``in_progress``.
        """

        run = await ctx.services.run.get()
        await ctx.services.events.publish(
            recorded(name),
            {"status": run.status.value, "output": run.output, "on": event.name},
        )

    # -- panels: every kind, every slot, both placements --------------------

    wf.panel("How to play", slot="workflow", kind="markdown", source=rules)
    wf.panel(
        "Round",
        slot="run",
        placement="card",
        kind="kv",
        source=round_,
        refresh_on=["run.*"],
    )
    wf.panel(
        "Words", slot="run", kind="table", source=words, refresh_on=["log.appended"]
    )
    wf.panel(
        "History",
        slot="run",
        kind="log",
        source=history,
        refresh_on=["task.*", "log.appended"],
    )
    wf.panel(
        "Scores", slot="run", kind="chart", source=scores, refresh_on=["task.done"]
    )
    wf.panel(
        "Summary", slot="run", kind="dashboard", source=summary, refresh_on=["run.*"]
    )
    wf.panel("Override", slot="task", kind="form", source=override)
    wf.panel("Playfield", slot="global", kind="custom", element=ELEMENT)
    wf.panel(
        "Verdict",
        slot="node",
        node="judge",
        kind="kv",
        source=verdict,
        refresh_on=["task.done"],
    )
    return wf


def _word_row(entry: LogEntryRow) -> dict[str, Any]:
    """One row of the ``table`` panel, from a work-log entry."""

    return {
        "node": entry.node,
        "word": entry.text.removeprefix("word:").strip(),
        "author": entry.author.value,
    }


def _log_row(event: EventRow) -> dict[str, Any]:
    """One row of the ``log`` panel: 09's ``{ts, text, level?}``."""

    row: dict[str, Any] = {
        "ts": event.created.isoformat(),
        "text": event.name,
    }
    if event.name.startswith("plugin."):
        row["level"] = "accent"
    return row
