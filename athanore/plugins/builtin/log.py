"""The log pane: the work log and the run's history, merged by time.

09 §Builtins are plugins: "run pane `log` sourced from the work log +
events, refresh on `log.appended` and `task.*`". 10 §Panes fixes the row
— ``time · source · message`` — the tone classes, and which events are
*not* shown here.

Two sources, one list. The work log is what people and agents wrote (03
§LogEntry, D4: it is the inter-stage channel); the events are what the
engine did between those writes. Read separately, either one is a story
with holes in it — a deliverable with no edge before it, or an edge with
no deliverable after it — so they are merged on ``created`` and the
result is one ordered stream.

**What is left out**, from 10 §Panes: ``task.stream`` (two to three a
second per streaming task, and the agent pane owns it), ``submission.*``
and ``request.*`` (the requests pane owns them), ``log.appended`` (it
announces the entry this list already carries) and ``agent.stats`` (the
stats entry is already a work-log line, and the overview pane totals it).

``level`` is 10's tone rather than a severity: ``accent`` for the stats
lines, ``dim`` for the engine — its failures and every lifecycle event —
and ``default`` for what an agent or a person wrote. The ``log`` kind of
09 gives a row one optional field to be coloured by, and 10 names exactly
three tones for this pane, so they are the same field.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from athanore.events.names import EventName, matches
from athanore.logging import get_logger
from athanore.plugins.context import PluginContext
from athanore.store.rows import EventRow, LogAuthor, LogEntryRow, LogKind
from athanore.workflow import Workflow

__all__ = ["declare"]

_log = get_logger(__name__)

#: Event names this pane does not show (10 §Panes). Globs, matched a
#: segment at a time by :func:`athanore.events.names.matches`.
HIDDEN: tuple[str, ...] = (
    EventName.task_stream.value,
    "submission.*",
    "request.*",
    EventName.log_appended.value,
    EventName.agent_stats.value,
)

#: The three tone classes of 10 §Panes, as the ``level`` of a row.
ACCENT = "accent"
DIM = "dim"
DEFAULT = "default"

#: What the source column reads for a line the engine produced from an
#: event rather than from a work-log entry.
ENGINE = LogAuthor.engine.value


def declare(wf_host: Workflow) -> None:
    """Declare the log route and its pane on ``wf_host``."""

    @wf_host.route("/log")
    async def log(ctx: PluginContext, limit: int | None = None) -> list[dict[str, Any]]:
        """The run's work log and its lifecycle events, oldest first.

        Whole by default — a run's log is bounded by the number of
        stages (08 §Agent-facing) and its events by the retention window
        (07) — and ``limit`` takes the most recent lines of the merged
        list, which is the end a pane that tails is reading.

        The attempts are read for their nodes: ``task.enqueued`` names
        the task an edge came *from*, and "engineering → qa" is what a
        reader of this pane came for.
        """

        entries = await ctx.services.run.log_entries()
        events = await ctx.services.run.events()
        _, tasks, _ = await ctx.services.run.detail()
        nodes = {task.id: task.node for task in tasks}
        lines = merge(entries, events, nodes)
        return lines[-limit:] if limit is not None and limit > 0 else lines

    wf_host.panel(
        "log",
        slot="run",
        kind="log",
        source=log,
        refresh_on=[EventName.log_appended.value, "task.*"],
    )


def merge(
    entries: list[LogEntryRow],
    events: list[EventRow],
    nodes: dict[int, str],
) -> list[dict[str, Any]]:
    """One list of rows, ordered by the time each thing happened.

    The tie-break is the source and then the id: two rows written in the
    same transaction share a timestamp to the microsecond often enough
    that leaving the order to the sort's stability would make it depend
    on which list was read first. A work-log entry sorts before an event
    of the same instant, because the entry is the thing that happened and
    the event announces it.
    """

    rows = [(entry.created, 0, entry.id, _entry_row(entry)) for entry in entries]
    rows += [
        (event.created, 1, event.id, _event_row(event, nodes))
        for event in events
        if _shown(event.name)
    ]
    rows.sort(key=lambda row: row[:3])
    return [row[3] for row in rows]


def _shown(name: str) -> bool:
    """Whether an event of this name belongs in the log pane."""

    return not any(matches(pattern, name) for pattern in HIDDEN)


def _entry_row(entry: LogEntryRow) -> dict[str, Any]:
    """One work-log entry as a row. The text is never truncated (03)."""

    return {
        "ts": entry.created.isoformat(),
        "source": f"{entry.node}/{entry.author.value}",
        "node": entry.node,
        "text": entry.text,
        "level": _tone(entry),
    }


def _tone(entry: LogEntryRow) -> str:
    """10 §Panes' tone mapping, on real work-log entries."""

    if entry.kind is LogKind.stats:
        return ACCENT
    if entry.author is LogAuthor.engine:
        return DIM
    return DEFAULT


def _event_row(event: EventRow, nodes: dict[int, str]) -> dict[str, Any]:
    """One lifecycle event as a row: dim, and one short sentence."""

    node = event.data.get("node")
    node = node if isinstance(node, str) else None
    return {
        "ts": event.created.isoformat(),
        "source": f"{node}/{ENGINE}" if node else ENGINE,
        **({"node": node} if node else {}),
        "text": sentence(event, nodes),
        "level": DIM,
    }


def sentence(event: EventRow, nodes: dict[int, str]) -> str:
    """``event`` as the one short line 10 §Panes asks for.

    Written from the 18 payload, and from ``nodes`` — the run's attempts
    by id — where the sentence names a node the payload only points at:
    ``task.enqueued`` carries the task it came *from*, and "engineering →
    qa" is the edge that made a reader ask for this pane in the first
    place.

    An event with no phrasing of its own falls back to its name. That is
    a name from the vocabulary of 03 rather than a placeholder, so a
    reader still sees what happened, and it is what keeps this pane
    correct when 03 gains a row before this module does.

    So does a payload a phrasing cannot read. The events table holds
    everything a run has ever emitted, including rows written by an
    older version of this process, and one of them missing a field is a
    reason to fall back to the name and say so in the log — not a reason
    for the whole pane to answer 500.
    """

    data = event.data
    render = _SENTENCES.get(event.name)
    if render is None:
        return event.name
    try:
        return render(data, nodes)
    except (KeyError, TypeError, ValueError):
        _log.warning(
            "a stored event does not match its payload",
            event_name=event.name,
            event_id=event.id,
        )
        return event.name


def _first_line(text: object) -> str:
    """The first line of an error, for a row that is one line."""

    return str(text).strip().splitlines()[0] if str(text).strip() else ""


def _enqueued(data: dict[str, Any], nodes: dict[int, str]) -> str:
    """The edge, the retry, or the reason the attempt exists."""

    node = data.get("node")
    reason = data.get("reason")
    attempt = data.get("attempt")
    origin = nodes.get(data["from_task"]) if data.get("from_task") is not None else None
    if reason == "start":
        return f"{node} queued"
    if reason in ("transition", "move") and origin is not None:
        arrow = f"{origin} → {node}"
        return arrow if reason == "transition" else f"{arrow} (moved)"
    if reason == "join":
        arrivals = data.get("arrivals") or []
        return f"{node} joined {len(arrivals)} branches"
    if reason in ("retry", "manual_retry"):
        return f"{node} retrying, attempt {attempt}"
    if reason == "rerun":
        return f"{node} rerun, attempt {attempt}"
    return f"{node} queued ({reason})"


#: One phrasing per event name (18 §Payloads). Each takes the payload
#: and the run's attempts by id, and answers with one line.
_SENTENCES: dict[str, Callable[[dict[str, Any], dict[int, str]], str]] = {
    EventName.run_created.value: lambda data, nodes: (
        f"run created in {data['workflow']} at position {data['position']}"
    ),
    EventName.run_started.value: lambda data, nodes: f"run started at {data['node']}",
    EventName.run_updated.value: lambda data, nodes: (
        "run edited: " + ", ".join(sorted(data.get("changed", {})))
    ),
    EventName.run_reordered.value: lambda data, nodes: (
        f"run moved from position {data['previous']} to {data['position']}"
    ),
    EventName.run_paused.value: lambda data, nodes: "run paused",
    EventName.run_resumed.value: lambda data, nodes: "run resumed",
    EventName.run_cancelled.value: lambda data, nodes: (
        f"run cancelled, {len(data.get('cancelled_tasks', []))} attempts stopped"
    ),
    EventName.run_deleted.value: lambda data, nodes: "run deleted",
    EventName.run_completed.value: lambda data, nodes: (
        f"run completed at {data['node']}"
    ),
    EventName.run_failed.value: lambda data, nodes: (
        f"run failed at {data['node']}: {_first_line(data.get('error'))}"
    ),
    EventName.task_enqueued.value: _enqueued,
    EventName.join_arrived.value: lambda data, nodes: (
        f"{data['join']} {data['arrived']} of {data['count']} arrived"
        + (" (late)" if data.get("late") else "")
    ),
    EventName.task_started.value: lambda data, nodes: (
        f"attempt {data['attempt']} started"
    ),
    EventName.task_done.value: lambda data, nodes: (
        f"attempt {data['attempt']} done"
        + (
            f" → {', '.join(data['transitions'])}"
            if data.get("transitions")
            else " (terminal)"
            if data.get("terminal")
            else ""
        )
    ),
    EventName.task_failed.value: lambda data, nodes: (
        f"attempt {data['attempt']} failed: {_first_line(data.get('error'))}"
        + (", retrying" if data.get("will_retry") else "")
    ),
    EventName.task_dead_lettered.value: lambda data, nodes: (
        f"attempt {data['attempt']} dead-lettered: {_first_line(data.get('error'))}"
    ),
    EventName.task_waiting.value: lambda data, nodes: (
        f"waiting on request {data['request_id']}"
    ),
    EventName.task_resumed.value: lambda data, nodes: (
        f"resumed after {data['waited_s']:.1f}s"
    ),
    EventName.task_cancelled.value: lambda data, nodes: f"cancelled ({data['reason']})",
    EventName.task_moved.value: lambda data, nodes: f"moved to {data['to']}",
    EventName.task_status_set.value: lambda data, nodes: (
        f"status set {data['from']} → {data['to']}"
    ),
}
