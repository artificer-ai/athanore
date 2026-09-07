"""The read-only verbs: submit work, then look at what happened (11 §Verbs).

Every verb here is one or more ``GET``s and a rendering of what came
back. Three rules run through all of them, and they are what make the
set feel like one tool rather than eight:

- **``--json`` is the API's own shape.** Not a second rendering of the
  table through another code path: the value the server sent, whole and
  unprojected, so ``athanore ls --json | jq`` reads the wire contract and
  a script never parses a table. What the table shows is a *projection*
  of that value — a joined list, an age in minutes, a suffix on a
  workflow no longer registered — and the projection exists only on the
  human path.

- **A follow is the SSE feed, resumed by id.** ``--watch`` and ``-f`` use
  :meth:`athanore.cli.client.Client.events`, the same iterator the tests
  read the stream through, and keep the last stored event id they saw so
  a stream that drops reconnects from there instead of replaying from
  zero (17 §T054). A ``resync`` frame means the server would not replay
  that far, so the follower fills the hole over REST rather than printing
  a history with a silent gap in it.

- **Following ends when the operator or the server ends it.** Ctrl-C is
  the ordinary way to stop one and exits 0; a server that cannot be
  reconnected to is 11 §Exit codes' 3, from
  :func:`athanore.cli.output.dispatch`, because at that point there is
  genuinely no server there.

``submit`` is here rather than with the steering verbs because the
bare-workflow alias resolves to it (:class:`athanore.cli.WorkflowAliasGroup`)
and because it is the one write every read in this module is about.
"""

from __future__ import annotations

import time
import webbrowser
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Annotated, Any, Final

import typer
from rich.console import Console
from rich.markup import escape

from athanore.cli import Options, app
from athanore.cli.client import Client, ServerEvent
from athanore.cli.output import Column, TableSpec, emit

__all__ = [
    "EVENTS",
    "LOG",
    "NODES",
    "PAGE",
    "RECONNECT_DELAY",
    "REQUESTS",
    "RESYNC",
    "RUNS",
    "TASKS",
    "follow",
    "logs",
    "ls",
    "open_spa",
    "requests",
    "show",
    "stream",
    "submit",
    "workflows",
]

#: How many rows a paging read asks for at a time. The API caps a page of
#: events or of transcript chunks at 5000 and defaults to 500 (08
#: §Conventions); this is the CLI's own step, and every verb that pages
#: loops until a short page rather than stopping at one of them.
PAGE: Final = 500

#: How long to wait before reconnecting a stream that ended. Short enough
#: that a follower resumes without the operator noticing, long enough
#: that a server refusing connections is not hammered.
RECONNECT_DELAY: Final = 0.5

#: The control frame 08 §Events sends instead of a replay the store could
#: not serve. It carries no event, so it is matched by name.
RESYNC: Final = "resync"

#: The name glob that selects every task-scoped event, which is what
#: `stream -f` watches: `task.stream` says the transcript grew, and the
#: terminal ones say it will not grow again.
_TASK_EVENTS: Final = "task.*"

#: The events that can change a row of the run list: a run's own state, a
#: task moving between nodes, a request opening or being answered.
WATCHED: Final = ("run.*", "task.*", "request.*")


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------

#: The run list (`ls`). `#` is the dispatch position, which is the order
#: the rows are already in, and `REQ` is how many people-shaped things
#: the run is waiting on.
RUNS: Final[TableSpec] = (
    Column("#", "position"),
    Column("RUN", "id"),
    Column("WORKFLOW", "workflow"),
    Column("STATUS", "status"),
    Column("NODE", "node"),
    Column("REQ", "requests"),
    Column("TITLE", "title"),
)

#: A run's attempts (`show`). One row per task row, oldest first.
TASKS: Final[TableSpec] = (
    Column("TASK", "id"),
    Column("NODE", "node"),
    Column("TRY", "attempt"),
    Column("STATUS", "status"),
    Column("ERROR", "error"),
)

#: A run's work log (`show`). The text is never truncated — it is the
#: inter-stage channel (D4) and half of it is the deliverable.
LOG: Final[TableSpec] = (
    Column("#", "id"),
    Column("NODE", "node"),
    Column("AUTHOR", "author"),
    Column("KIND", "kind"),
    Column("TEXT", "text"),
)

#: A run's stored events (`logs`, without `-f`).
EVENTS: Final[TableSpec] = (
    Column("#", "id"),
    Column("EVENT", "name"),
    Column("TASK", "task_id"),
    Column("CREATED", "created"),
    Column("DATA", "data"),
)

#: One workflow's nodes (`workflows`), which is the graph 11 asks for.
NODES: Final[TableSpec] = (
    Column("NODE", "name"),
    Column("GEN", "generation"),
    Column("EDGES", "edges"),
    Column("PRIORITY", "priority"),
    Column("RETRIES", "retries"),
    Column("TIMEOUT", "timeout"),
)

#: The requests waiting on a person (`requests`).
REQUESTS: Final[TableSpec] = (
    Column("REQ", "id"),
    Column("RUN", "run_id"),
    Column("NODE", "node"),
    Column("MODE", "mode"),
    Column("KIND", "kind"),
    Column("AGE", "age"),
    Column("OPTIONS", "options"),
    Column("PROMPT", "prompt"),
)


# --------------------------------------------------------------------------
# The shared shape of a verb
# --------------------------------------------------------------------------


def console() -> Console:
    """A console for the lines a table spec cannot carry.

    Built per call, like :func:`athanore.cli.output.emit`'s: pytest swaps
    ``sys.stdout`` between phases and a console captured at import would
    write to whichever stream existed first.
    """

    return Console()


def line(text: str) -> None:
    """Print one line of the CLI's own prose, markup-free.

    Escaped, never interpreted: the text carries a title, a prompt or an
    agent's transcript, and ``[stats]`` is a log line rather than a style
    tag.
    """

    console().print(escape(text), highlight=False)


def render(
    options: Options,
    data: Any,
    spec: TableSpec | None = None,
    rows: Sequence[Any] | None = None,
) -> None:
    """Emit ``data`` as the API sent it, or ``rows`` under ``spec``.

    The two arguments are the whole of "``--json`` emits the API shape":
    ``data`` is what the server said and is what ``--json`` prints, and
    ``rows`` is the projection of it that the table columns name. A verb
    whose response needs no projection passes only ``data``.
    """

    emit(
        data if options.json or rows is None else rows,
        spec,
        options.json,
    )


@contextmanager
def until_interrupted() -> Iterator[None]:
    """Run a follow loop until Ctrl-C, which ends it successfully.

    Ctrl-C is how an operator stops ``-f``; it is the verb finishing, not
    the verb failing, so it does not reach
    :func:`athanore.cli.output.dispatch` and does not become an exit
    status. Everything else propagates.
    """

    try:
        yield
    except KeyboardInterrupt:
        # A newline, because the terminal has just echoed `^C` and the
        # next shell prompt would otherwise land on the same line.
        console().print()


def follow(
    client: Client,
    *,
    run: str | None = None,
    names: Sequence[str] | None = None,
    after: int | None = None,
) -> Iterator[ServerEvent]:
    """The event feed, reconnected from the last stored id when it ends.

    ``after`` is advanced by every frame that carried one — which is
    every stored event, and no ephemeral one (08 §Events) — so a stream
    that drops resumes from the last event this iterator actually yielded
    rather than replaying the run from the beginning.

    A stream that ends is reconnected, because ending is what a dropped
    connection, a restarted proxy and a graceful server shutdown all look
    like from here and only the third of them is final. The third one
    then refuses the reconnect, which is an
    :exc:`httpx.TransportError` and 11 §Exit codes' 3: there is no server
    there any more, and saying so is more use than a follower that waits
    for one for ever.
    """

    cursor = after
    while True:
        for event in client.events(after=cursor, names=names, run=run):
            if event.id is not None:
                cursor = event.id
            yield event
        time.sleep(RECONNECT_DELAY)


# --------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------


def _mappings(value: Any) -> list[Mapping[str, Any]]:
    """``value`` as the list of objects the API documents it to be."""

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _mapping(value: Any) -> Mapping[str, Any]:
    """``value`` as the object the API documents it to be."""

    return value if isinstance(value, Mapping) else {}


def _join(value: Any) -> str:
    """A list field as one cell: comma-separated, empty when it is empty."""

    if not isinstance(value, list):
        return ""
    return ", ".join(str(item) for item in value)


def _age(seconds: Any) -> str:
    """Seconds since a request was opened, as a person reads them."""

    if not isinstance(seconds, (int, float)):
        return ""
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def _run_row(run: Mapping[str, Any]) -> dict[str, Any]:
    """One row of the run list, projected onto :data:`RUNS`.

    ``unregistered`` becomes a suffix on the workflow rather than a
    column of its own: it is rare, it is the reason nothing about the run
    is moving, and a column of blanks would cost every other row width to
    say so (03 §Run).
    """

    workflow = str(run.get("workflow", ""))
    if run.get("unregistered"):
        workflow = f"{workflow} (unregistered)"
    return {
        "position": run.get("position"),
        "id": run.get("id"),
        "workflow": workflow,
        "status": run.get("status"),
        "node": _join(run.get("current_nodes")),
        "requests": run.get("pending_requests"),
        "title": run.get("title"),
    }


def _node_row(name: str, node: Mapping[str, Any]) -> dict[str, Any]:
    """One node of a workflow's graph, projected onto :data:`NODES`."""

    return {
        "name": name,
        "generation": node.get("generation"),
        "edges": _join(node.get("edges")) or "(terminal)",
        "priority": node.get("priority"),
        "retries": node.get("retries"),
        "timeout": node.get("timeout"),
    }


def _request_row(view: Mapping[str, Any]) -> dict[str, Any]:
    """One request, projected onto :data:`REQUESTS`."""

    options = [
        str(option.get("option_id"))
        for option in _mappings(view.get("options"))
        if "option_id" in option
    ]
    return {
        "id": view.get("id"),
        "run_id": view.get("run_id"),
        "node": view.get("node"),
        "mode": view.get("mode"),
        "kind": view.get("kind"),
        "age": _age(view.get("age")),
        "options": ", ".join(options),
        "prompt": view.get("prompt"),
    }


def _event_line(event: Mapping[str, Any]) -> str:
    """One stored event as a line, for the half of ``logs`` that follows.

    A table cannot grow a row at a time, so a followed feed is lines and
    a stored page is a table. The invocation decides which: ``logs -f``
    prints its first page as lines too, so what scrolls past is one
    shape.
    """

    identifier = event.get("id")
    where = f"[{identifier}]" if identifier is not None else "[live]"
    task = f" task={event['task_id']}" if event.get("task_id") is not None else ""
    data = event.get("data")
    payload = f" {data}" if data else ""
    return f"{where} {event.get('name')}{task}{payload}"


# --------------------------------------------------------------------------
# Reading a run's history
# --------------------------------------------------------------------------


def _events_page(client: Client, run: str, after: int) -> list[Mapping[str, Any]]:
    """One page of ``GET /api/runs/{id}/events`` after ``after``."""

    return _mappings(
        client.get(f"/api/runs/{run}/events", params={"after": after, "limit": PAGE})
    )


def _all_events(client: Client, run: str, after: int = 0) -> list[Mapping[str, Any]]:
    """Every stored event of ``run`` after ``after``, paging until the end.

    The API pages this list, and a verb that printed one page and stopped
    would be a verb that quietly lost a run's history at 500 events.
    """

    history: list[Mapping[str, Any]] = []
    while True:
        page = _events_page(client, run, after)
        history.extend(page)
        if len(page) < PAGE:
            return history
        last = page[-1].get("id")
        if not isinstance(last, int) or last <= after:
            # Ids ascend (`EventRepo`); a page that did not advance the
            # cursor would loop for ever, and stopping is the only honest
            # thing left to do with it.
            return history
        after = last


# --------------------------------------------------------------------------
# The verbs
# --------------------------------------------------------------------------


@app.command()
def submit(
    ctx: typer.Context,
    workflow: Annotated[str, typer.Argument(help="The workflow to run.")],
    title: Annotated[str, typer.Argument(help="The operator's title for the run.")],
    description: Annotated[
        str, typer.Argument(help="Longer context; the workflow's input.")
    ] = "",
) -> None:
    """Queue a run of a workflow.

    ``athanore <workflow> "<title>"`` is the same thing: the MVP's
    shorthand is kept as an alias of this verb (11 §Verbs), resolved by
    :class:`athanore.cli.WorkflowAliasGroup`.
    """

    options = Options.of(ctx)
    with options.client() as client:
        created = client.post(
            f"/api/workflows/{workflow}/runs",
            {"title": title, "description": description},
        )
    render(options, created)


@app.command("ls")
def ls(
    ctx: typer.Context,
    status: Annotated[
        str | None, typer.Option("--status", help="Only runs in this status.")
    ] = None,
    workflow: Annotated[
        str | None, typer.Option("--workflow", help="Only runs of this workflow.")
    ] = None,
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Redraw the list as runs change, until Ctrl-C."),
    ] = False,
) -> None:
    """List the runs, in the order the scheduler will claim them."""

    options = Options.of(ctx)
    params = {"status": status, "workflow": workflow}
    with options.client() as client:
        _draw_runs(options, client, params)
        if not watch:
            return
        with until_interrupted():
            for _ in follow(client, names=WATCHED):
                # Every frame is a redraw, including `resync`: the list is
                # a whole read of the API rather than a history to catch
                # up on, so there is no hole for a missed event to leave.
                console().print()
                _draw_runs(options, client, params)


def _draw_runs(options: Options, client: Client, params: Mapping[str, Any]) -> None:
    """One rendering of the run list, table or JSON."""

    runs = client.get("/api/runs", params=params)
    render(options, runs, RUNS, [_run_row(run) for run in _mappings(runs)])


@app.command()
def show(
    ctx: typer.Context,
    run: Annotated[str, typer.Argument(help="The run id.")],
) -> None:
    """A run, its attempts and its work log.

    ``--json`` is the ``RunDetail`` of 08 §Runs with the run's work log
    added under ``log``: every key is the API's own, and the two reads
    that produced them are one object rather than something a script has
    to reassemble.
    """

    options = Options.of(ctx)
    with options.client() as client:
        detail = _mapping(client.get(f"/api/runs/{run}"))
        log = _mappings(client.get(f"/api/runs/{run}/log"))
    if options.json:
        emit({**detail, "log": log}, json_flag=True)
        return
    line(
        f"run {detail.get('id')}  workflow={detail.get('workflow')}  "
        f"status={detail.get('status')}  position={detail.get('position')}"
    )
    line(f"title: {detail.get('title')}")
    if detail.get("description"):
        line(f"description: {detail['description']}")
    if detail.get("output") is not None:
        line(f"output: {detail['output']}")
    tasks = _mappings(detail.get("tasks"))
    if tasks:
        console().print()
        emit(tasks, TASKS)
    if log:
        console().print()
        emit(log, LOG)


@app.command()
def logs(
    ctx: typer.Context,
    run: Annotated[str, typer.Argument(help="The run id.")],
    follow_: Annotated[
        bool,
        typer.Option("-f", "--follow", help="Keep printing events as they happen."),
    ] = False,
) -> None:
    """A run's events: its history, and with -f what happens next."""

    options = Options.of(ctx)
    with options.client() as client:
        history = _all_events(client, run)
        if not follow_:
            render(options, history, EVENTS)
            return
        for event in history:
            _print_event(options, event)
        cursor = _last_id(history)
        with until_interrupted():
            for frame in follow(client, run=run, after=cursor):
                if frame.name == RESYNC:
                    # The server would not replay that far, so it sent
                    # nothing: the hole is filled over REST rather than
                    # printed as a history that silently skips.
                    for missed in _all_events(client, run, cursor):
                        _print_event(options, missed)
                        cursor = missed.get("id") or cursor
                    continue
                _print_event(options, _mapping(frame.data))
                if frame.id is not None:
                    cursor = frame.id


def _last_id(events: Sequence[Mapping[str, Any]]) -> int:
    """The highest stored id in a page, or 0 for an empty one."""

    for event in reversed(events):
        identifier = event.get("id")
        if isinstance(identifier, int):
            return identifier
    return 0


def _print_event(options: Options, event: Mapping[str, Any]) -> None:
    """One event, as JSON or as a line."""

    if options.json:
        emit(event, json_flag=True)
        return
    line(_event_line(event))


@app.command()
def stream(
    ctx: typer.Context,
    task: Annotated[int, typer.Argument(help="The task id.")],
    follow_: Annotated[
        bool,
        typer.Option(
            "-f", "--follow", help="Keep printing the transcript as it grows."
        ),
    ] = False,
) -> None:
    """One attempt's agent transcript.

    ``-f`` follows it the way 08 §Events says a client does: the
    ephemeral ``task.stream`` event says the transcript grew, and the
    chunks themselves come from ``GET /api/tasks/{id}/stream`` — which is
    what keeps the event feed small and lets a late joiner catch up.
    Following ends when the attempt does, because a transcript that can
    no longer grow has nothing left to say.
    """

    options = Options.of(ctx)
    with options.client() as client:
        detail = _mapping(client.get(f"/api/tasks/{task}"))
        page = _mapping(client.get(f"/api/tasks/{task}/stream", params={"limit": PAGE}))
        chunks = _mappings(page.get("chunks"))
        if options.json:
            emit(page, json_flag=True)
        else:
            _print_chunks(chunks)
        if not follow_ or not page.get("live"):
            return
        seq = _last_seq(chunks)
        run = str(detail.get("run_id"))
        with until_interrupted():
            for frame in follow(client, run=run, names=[_TASK_EVENTS]):
                # Every envelope of a task-scoped event carries its
                # `task_id` (18 §Typing), and a `resync` carries none —
                # which is the one frame worth reacting to blindly, since
                # it says a transcript may have grown unobserved.
                if frame.name != RESYNC and _mapping(frame.data).get("task_id") != task:
                    continue
                seq, live = _drain(options, client, task, seq)
                if not live:
                    return


def _print_chunks(chunks: Sequence[Mapping[str, Any]]) -> None:
    """A transcript's chunks, as the text they are.

    No table: a transcript is prose, and the kind is a prefix only where
    it changes what the text *is* — a thought, a tool call, a notice the
    façade wrote — rather than the assistant simply talking (05 §The ACP
    client).
    """

    for chunk in chunks:
        kind = str(chunk.get("kind", ""))
        text = str(chunk.get("text", ""))
        line(text if kind == "text" else f"[{kind}] {text}")


def _last_seq(chunks: Sequence[Mapping[str, Any]]) -> int:
    """The highest sequence number in a page of chunks, or 0."""

    for chunk in reversed(chunks):
        seq = chunk.get("seq")
        if isinstance(seq, int):
            return seq
    return 0


def _drain(options: Options, client: Client, task: int, seq: int) -> tuple[int, bool]:
    """Print everything after ``seq``; report the new cursor and liveness."""

    page = _mapping(
        client.get(f"/api/tasks/{task}/stream", params={"after": seq, "limit": PAGE})
    )
    chunks = _mappings(page.get("chunks"))
    if options.json:
        if chunks:
            emit(page, json_flag=True)
    else:
        _print_chunks(chunks)
    return max(seq, _last_seq(chunks)), bool(page.get("live"))


@app.command()
def workflows(ctx: typer.Context) -> None:
    """The workflows this server runs: their graphs and their pools."""

    options = Options.of(ctx)
    with options.client() as client:
        listed = client.get("/api/workflows")
    if options.json:
        emit(listed, json_flag=True)
        return
    out = console()
    for index, workflow in enumerate(_mappings(listed)):
        if index:
            out.print()
        line(
            f"{workflow.get('name')}  start={workflow.get('start')}  "
            f"pool={workflow.get('pool')} "
            f"{workflow.get('in_flight')}/{workflow.get('capacity')}"
        )
        nodes = _mapping(workflow.get("nodes"))
        emit(
            [_node_row(name, _mapping(node)) for name, node in nodes.items()],
            NODES,
        )


@app.command()
def requests(
    ctx: typer.Context,
    run: Annotated[
        str | None, typer.Argument(help="Only the requests of this run.")
    ] = None,
) -> None:
    """The requests waiting on a person, across every run or in one.

    Pending, not merely unanswered: a request whose attempt has ended is
    stale and cannot be answered, so it stays in the run's history and
    leaves this list (06 §Restart durability).
    """

    options = Options.of(ctx)
    with options.client() as client:
        views = client.get("/api/requests", params={"pending": True, "run": run})
    render(options, views, REQUESTS, [_request_row(v) for v in _mappings(views)])


@app.command("open")
def open_spa(
    ctx: typer.Context,
    run: Annotated[
        str | None, typer.Argument(help="The run to open; the run list without one.")
    ] = None,
) -> None:
    """Open the operator interface in a browser.

    A named run is read first, so a run id that does not exist is a 404
    with the server's own message rather than a browser tab pointed at
    nothing. The route is the SPA's linkable state: one route with
    ``?run=`` (10 §Routing).
    """

    options = Options.of(ctx)
    with options.client() as client:
        if run is not None:
            client.get(f"/api/runs/{run}")
        url = client.url if run is None else f"{client.url}/?run={run}"
    webbrowser.open(url)
    render(options, {"url": url})
