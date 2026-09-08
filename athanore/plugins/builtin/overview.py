"""The overview pane: what a run cost, what it is, and what it did.

09 §Builtins are plugins gives it one row — "run pane (`dashboard`:
metric tiles, token bars, `kv` meta, `table` nodes)" — and 10 §Panes
fixes every field it shows. One route and one panel: the panel is a
``dashboard`` in the ``run`` slot, and the route is where its data comes
from.

The response is the ``dashboard`` shape of 09 §Panel kinds — ``note``,
``metrics``, ``table`` — plus a ``meta`` object, which is the two-column
`kv` grid 10 puts between the tiles and the NODES table. A renderer that
knows only the ``dashboard`` kind draws the first three and ignores the
fourth; the SPA's own overview renderer draws all of it. Adding a key is
what the declared kind allows; inventing a kind for one pane is not.

**Nothing is zero-filled.** A metric whose fact is unknown is *absent*
(01 §Real data only), so a run on which no agent has yet reported
anything shows two tiles rather than four claiming zero tokens and no
cost. The same rule runs through the node table — a node with no stats
entry carries no ``tokens`` key — and through ``meta``, where SESSION is
there only once an agent has run.

10's per-node token bars are drawn from the same ``table`` rows the NODES
grid is: the bar and the cell are one number, and sending it twice is how
they would come to differ.

**The totals are the run's totals.** They come from ``RunRepo.detail``,
the one read ``GET /api/runs/{id}`` makes, so the tile and
``RunDetail.stats`` are the same number from the same query rather than
two sums that can drift.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from athanore.plugins.context import PluginContext
from athanore.store.clock import now
from athanore.store.rows import RunRow, RunStats, TaskRow, TaskStatus
from athanore.workflow import Workflow

__all__ = ["declare"]

#: The columns of the NODES table, in the order 10 §Panes draws them.
#: ``kind`` is the column hint of 09 §Panel kinds: it says what the value
#: is, not how wide to draw it.
COLUMNS: list[dict[str, str]] = [
    {"key": "node", "label": "NODE", "kind": "text"},
    {"key": "attempts", "label": "ATT", "kind": "number"},
    {"key": "status", "label": "STATUS", "kind": "status"},
    {"key": "tokens", "label": "TOKENS", "kind": "number"},
    {"key": "duration_s", "label": "DUR", "kind": "duration"},
]

#: The attempt statuses that put a run "in" a node right now. The same
#: pair ``RunRepo.list`` aggregates ``current_nodes`` from and the same
#: pair ``GET /api/runs/{id}`` recomputes, so the pane and the run row
#: cannot disagree about which nodes are live.
IN_FLIGHT = frozenset({TaskStatus.in_progress, TaskStatus.waiting})


def declare(wf_host: Workflow) -> None:
    """Declare the overview route and its pane on ``wf_host``."""

    @wf_host.route("/overview")
    async def overview(ctx: PluginContext) -> dict[str, Any]:
        """A run's totals, its meta, and a row per node it has entered."""

        run, tasks, stats = await ctx.services.run.detail()
        runs = [row.id for row in await ctx.services.run.list()]
        body: dict[str, Any] = {
            "metrics": _metrics(run, stats, runs),
            "table": {"columns": COLUMNS, "rows": _nodes(tasks)},
            "meta": _meta(run, tasks),
        }
        if run.description:
            body["note"] = run.description
        return body

    wf_host.panel(
        "overview",
        slot="run",
        kind="dashboard",
        source=overview,
        refresh_on=["run.*", "task.*", "agent.stats"],
    )


def _metrics(run: RunRow, stats: RunStats, runs: list[str]) -> list[dict[str, Any]]:
    """The four tiles of 10 §Panes, minus the ones nothing is known for.

    TOKENS and COST are the run's totals over **every** attempt, failed
    ones included — they were paid for (05 §Stats entry) — and each is
    absent when no attempt reported it. DURATION is wall-clock,
    ``finished − created`` or ``now − created``, which is a fact about
    every run from the moment it exists. POSITION is the run's place in
    the dispatch list, and it is the one tile whose value is a string:
    "4 of 12" is two numbers read together, and a tile shows one value.
    """

    metrics: list[dict[str, Any]] = []
    if stats.total_tokens is not None:
        metrics.append({"label": "TOKENS", "value": stats.total_tokens})
    if stats.cost is not None:
        metrics.append({"label": "COST", "value": stats.cost})
    metrics.append({"label": "DURATION", "value": _elapsed(run)})
    position = _position(run, runs)
    if position is not None:
        metrics.append({"label": "POSITION", "value": position})
    return metrics


def _elapsed(run: RunRow) -> float:
    """How long the run has been going, in seconds (10 §Panes)."""

    end = run.finished if run.finished is not None else now()
    return (end - run.created).total_seconds()


def _position(run: RunRow, runs: list[str]) -> str | None:
    """``"4 of 12"``: where the run sits in the dispatch list.

    ``runs`` is the list in dispatch order, which for the builtin scope
    is every run there is. ``None`` when the run is not in it — a run
    deleted between the two reads — because a place in a list the run is
    not in is not a fact (01 §Real data only).
    """

    if run.id not in runs:
        return None
    return f"{runs.index(run.id) + 1} of {len(runs)}"


def _meta(run: RunRow, tasks: list[TaskRow]) -> dict[str, Any]:
    """The `kv` grid of 10 §Panes, in its order.

    STATUS carries the nodes the run is in right now, joined the way the
    run list joins them. SESSION is the agent session of the most recent
    attempt that reported one, whole rather than shortened — how many
    characters of it to show is the renderer's decision. AGENTS counts
    the attempts that carry a stats entry. Both are absent until an agent
    has run, and DESCRIPTION until the operator has written one — which
    is not the same absence: 10 §Panes drops SESSION and AGENTS from the
    grid and draws "DESCRIPTION is the run's, or `—`", so the renderer
    supplies the dash for the key this omits (15, D161).
    """

    meta: dict[str, Any] = {
        "RUN": run.id,
        "WORKFLOW": run.workflow,
        "TITLE": run.title,
        "STATUS": _status(run, tasks),
        "AGE": (now() - run.created).total_seconds(),
    }
    session = _session(tasks)
    if session is not None:
        meta["SESSION"] = session
    agents = sum(1 for task in tasks if task.stats)
    if agents:
        meta["AGENTS"] = agents
    if run.description:
        meta["DESCRIPTION"] = run.description
    return meta


def _status(run: RunRow, tasks: list[TaskRow]) -> str:
    """The run status, and the nodes it is in when it is in any.

    10 §Panes asks for the nodes on a ``running`` run; the condition here
    is that there *are* in-flight attempts, which is the same set on a
    running run and is honest on the ones where the two disagree — a
    paused run whose last attempt is still finishing has a node, and
    hiding it would be hiding the reason it has not stopped yet.
    """

    live = sorted({task.node for task in tasks if task.status in IN_FLIGHT})
    if not live:
        return run.status.value
    return f"{run.status.value} · {' · '.join(live)}"


def _session(tasks: list[TaskRow]) -> str | None:
    """The ``session_id`` of the most recent attempt that reported one."""

    for task in reversed(tasks):
        session = (task.stats or {}).get("session_id")
        if isinstance(session, str) and session:
            return session
    return None


def _nodes(tasks: list[TaskRow]) -> list[dict[str, Any]]:
    """One row per node the run has entered, in the order it entered them.

    Attempts of one node collapse into one row: ATT is how many there
    have been, STATUS is the latest one's, TOKENS is what they spent
    between them, and DUR is how long they took. A node the run has not
    reached has no attempt and therefore no row — the graph pane is
    where the shape of the whole workflow is drawn, and this table is the
    history.

    DUR is wall-clock, ``finished − started`` summed over the attempts
    that have both, to match the DURATION tile; the agent's own
    ``duration_s`` is a different measurement and lives in the stats
    entry. A row omits ``tokens`` or ``duration_s`` outright when nothing
    is known, rather than showing a zero nobody measured.
    """

    rows: dict[str, dict[str, Any]] = {}
    for task in tasks:
        row = rows.setdefault(
            task.node, {"node": task.node, "attempts": 0, "status": task.status.value}
        )
        row["attempts"] += 1
        row["status"] = task.status.value
        tokens = (task.stats or {}).get("total_tokens")
        if isinstance(tokens, int):
            row["tokens"] = row.get("tokens", 0) + tokens
        elapsed = _attempt_seconds(task)
        if elapsed is not None:
            row["duration_s"] = row.get("duration_s", 0.0) + elapsed
    return list(rows.values())


def _attempt_seconds(task: TaskRow) -> float | None:
    """How long one attempt took, or ``None`` if it is not known yet."""

    started: datetime | None = task.started
    finished: datetime | None = task.finished
    if started is None or finished is None:
        return None
    return (finished - started).total_seconds()
