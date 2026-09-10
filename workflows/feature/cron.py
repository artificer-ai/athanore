"""Scheduled runs: a crontab for every workflow this host serves.

**Why this is a plugin plus a ticker, and not a plugin alone.** 09 gives
a workflow four declarations — a route, an action, a panel and an ``on``
handler — and none of them is a clock. ``on`` fires when an event is
emitted, so a cron built on it would never fire on a quiet server, which
is exactly when a schedule matters. The surface is therefore a plugin and
the *firing* is a task started by the host through
``Server.serve(on_start=...)`` (04 §Programmatic host), which
:mod:`workflows.__main__` owns and is allowed to change.

**"Global" here is a placement, not an owner.** The pane is declared with
``slot="global"`` — shown when no run is selected — but every plugin
belongs to a workflow: routes mount under ``/api/plugins/{workflow}/``
and the manifest is per workflow. So this is declared on ``feature`` and
schedules *everything*, which it can do because
:attr:`~athanore.plugins.context.PluginContext.ops` is "the operator
operations of 04, unscoped by design": every one of them takes an
explicit id, so an action that submits a run of another workflow is the
same call as one that submits its own. That an app-level concern has to
name an owning workflow is the open question in `TODO.md`, not something
settled here.

**The state is a file, not a table.** A plugin cannot add a table — the
store's schema is Alembic's and 07's — so schedules live in
``.athanore/schedules.json``, beside the drop box and git-ignored for the
same reason: nothing here may dirty a checkout that `feature` is about
to branch from.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from athanore import PluginContext, PluginError, Workflow

from .sandbox import CHECKOUT

if TYPE_CHECKING:
    from athanore import Server

__all__ = ["FIELDS", "SCHEDULES", "declare", "matches", "next_fire", "start_ticker"]

#: Where the crontab lives. Git-ignored, like everything under
#: `.athanore/`, so editing it can never dirty the tree a run branches
#: from.
SCHEDULES = CHECKOUT / ".athanore" / "schedules.json"

#: The five fields, in order, with the range each accepts. Day-of-week is
#: 0-6 with 0 = Monday, matching ``datetime.weekday()`` rather than
#: cron's Sunday-first convention — this is a fresh crontab, not a POSIX
#: one, and agreeing with the language it is written in beats agreeing
#: with a tradition nobody here is porting from. The pane says so.
FIELDS: tuple[tuple[str, int, int], ...] = (
    ("minute", 0, 59),
    ("hour", 0, 23),
    ("day of month", 1, 31),
    ("month", 1, 12),
    ("day of week (0=Mon)", 0, 6),
)

#: How far ahead :func:`next_fire` will look before giving up. A schedule
#: that fires less than once a fortnight is one whose next time is not
#: worth a minute of stepping to find.
HORIZON = timedelta(days=14)

_TERM = re.compile(r"^(?:\*|(\d+)(?:-(\d+))?)(?:/(\d+))?$")

#: The one lock over the file. Every reader and writer is on the server's
#: event loop — the routes and the ticker both — so one asyncio lock is
#: the whole of the concurrency story.
_lock = asyncio.Lock()

#: Set by :func:`start_ticker`, read by the route that lists workflows.
#: Dev machinery reaching into its own host, deliberately: there is no
#: seam on `PluginContext` that names the workflows a server runs, and
#: inventing one to avoid a module global would be a change to `athanore`
#: for the benefit of a pane.
_server: Server | None = None


def _field(term: str, low: int, high: int, where: str) -> set[int]:
    """One cron field as the set of values it matches.

    ``*``, ``n``, ``a-b``, ``*/n`` and ``a-b/n``. A comma-separated list
    is the union of its parts, which is the caller's loop.
    """

    found = _TERM.match(term)
    if found is None:
        raise PluginError(400, f"{term!r} is not a {where} this crontab understands")
    start, end, step = found.groups()
    if start is None:
        first, last = low, high
    else:
        first = int(start)
        last = int(end) if end is not None else first
    every = int(step) if step is not None else 1
    if every < 1:
        raise PluginError(400, f"a step of {every} in {term!r} matches nothing")
    if first < low or last > high or first > last:
        raise PluginError(
            400, f"{term!r} is outside {where}, which runs {low} to {high}"
        )
    return set(range(first, last + 1, every))


def parse(expression: str) -> tuple[set[int], ...]:
    """A five-field expression as five sets, or raise.

    Raising rather than returning ``None`` because the only caller that
    cannot act on a bad expression is the one saving it, and a crontab
    that accepted a line it would never fire is worse than one that
    refused it while the operator was still looking.
    """

    terms = expression.split()
    if len(terms) != len(FIELDS):
        raise PluginError(
            400,
            f"a schedule has {len(FIELDS)} fields "
            f"({', '.join(name for name, _, _ in FIELDS)}); "
            f"{expression!r} has {len(terms)}",
        )
    return tuple(
        set().union(*(_field(part, low, high, name) for part in term.split(",")))
        for term, (name, low, high) in zip(terms, FIELDS, strict=True)
    )


def matches(expression: str, when: datetime) -> bool:
    """Whether ``expression`` fires in the minute ``when`` falls in.

    Day-of-month and day-of-week are **and**, not cron's "or when both
    are restricted". That rule exists so `0 0 1 * 1` can mean "the 1st
    and every Monday", and it surprises everyone who has not read the
    manual page; a crontab written this week does not have to inherit it.
    """

    minute, hour, dom, month, dow = parse(expression)
    return (
        when.minute in minute
        and when.hour in hour
        and when.day in dom
        and when.month in month
        and when.weekday() in dow
    )


def next_fire(expression: str, after: datetime) -> str | None:
    """The next minute at or after ``after`` that fires, ISO, or ``None``.

    Stepped a minute at a time rather than solved, because 20 000 cheap
    set lookups take a few milliseconds and a closed-form next-time is a
    well-known source of off-by-one bugs at month ends.
    """

    fields = parse(expression)
    cursor = (after + timedelta(minutes=1)).replace(second=0, microsecond=0)
    limit = after + HORIZON
    minute, hour, dom, month, dow = fields
    while cursor <= limit:
        if (
            cursor.minute in minute
            and cursor.hour in hour
            and cursor.day in dom
            and cursor.month in month
            and cursor.weekday() in dow
        ):
            return cursor.isoformat(timespec="minutes")
        cursor += timedelta(minutes=1)
    return None


def _read() -> list[dict[str, Any]]:
    """The crontab, or an empty one. A broken file is not a crash.

    An operator may edit this by hand — it is a JSON file in a directory
    they own — so a half-saved edit is an ordinary event. It reads as
    empty and the pane says nothing rather than the server refusing to
    answer, and the next write rewrites it whole.
    """

    if not SCHEDULES.is_file():
        return []
    try:
        loaded = json.loads(SCHEDULES.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return loaded if isinstance(loaded, list) else []


def _write(rows: list[dict[str, Any]]) -> None:
    """Replace the crontab, atomically."""

    SCHEDULES.parent.mkdir(parents=True, exist_ok=True)
    scratch = SCHEDULES.with_suffix(".json.tmp")
    scratch.write_text(json.dumps(rows, indent=2) + "\n")
    scratch.replace(SCHEDULES)


def _view(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    """One schedule as the pane reads it, with its next fire worked out."""

    try:
        upcoming = next_fire(row["cron"], now) if row.get("enabled", True) else None
    except PluginError:
        # A row whose expression no longer parses — hand-edited, most
        # likely. It is shown, and shown as never firing, rather than
        # taking the whole listing down with it.
        upcoming = None
    return {**row, "next": upcoming}


async def _fire(name: str, title: str, description: str) -> str:
    """Submit one run and return its id.

    Through ``ops`` rather than over HTTP: the ticker holds the server,
    so there is no bind to reach, no token to read and no request to
    authenticate. `planner` went over the wire because a *node body* has
    no ``ops`` by design (04 §TaskContext); the host does.
    """

    if _server is None:  # pragma: no cover - the ticker sets it before any tick
        raise PluginError(503, "the scheduler is not attached to a server yet")
    run = await _server.engine.ops.submit(name, title, description)
    return run.id


async def tick(now: datetime | None = None) -> list[dict[str, Any]]:
    """Fire every schedule due this minute. Returns what it submitted.

    **A minute fires at most once**, whatever the tick rate or a restart:
    `fired_minute` is the ISO minute a schedule last went off, and a
    schedule whose stored minute equals this one is skipped. Without it a
    ticker that woke twice inside one minute — or a server restarted at
    :30 — would submit the same run again, and a duplicate `feature` run
    is a second branch and a second gate.
    """

    when = (now or datetime.now()).replace(second=0, microsecond=0)
    stamp = when.isoformat(timespec="minutes")
    fired: list[dict[str, Any]] = []
    async with _lock:
        rows = _read()
        for row in rows:
            if not row.get("enabled", True) or row.get("fired_minute") == stamp:
                continue
            try:
                due = matches(row["cron"], when)
            except (PluginError, KeyError):
                continue
            if not due:
                continue
            row["fired_minute"] = stamp
            try:
                run_id = await _fire(
                    row["workflow"],
                    row.get("title") or row["cron"],
                    row.get("prompt", ""),
                )
            except Exception as exc:
                # A workflow that is no longer registered, or a refusal
                # from `ops`. The schedule is marked as having fired this
                # minute anyway, so a failing row does not retry sixty
                # times before the minute is out.
                row["last_error"] = str(exc)[:400]
                continue
            row.pop("last_error", None)
            row["last_run"] = run_id
            row["last_fired"] = int(time.time())
            fired.append({"id": row["id"], "workflow": row["workflow"], "run": run_id})
        _write(rows)
    return fired


async def _loop(server: Server) -> None:
    """Tick once a minute, on the minute, until cancelled.

    Woken just after the boundary rather than every 60 s from start-up,
    so `*/5` means the fifth minute of the hour and not five minutes
    after whenever the host happened to boot.
    """

    global _server
    _server = server
    while True:
        now = time.time()
        await asyncio.sleep(60 - (now % 60) + 0.5)
        with contextlib.suppress(Exception):
            # A tick that raised must not end the scheduler: the next
            # minute is a fresh attempt, and the alternative is a host
            # that silently stops scheduling and looks healthy.
            await tick()


def start_ticker(server: Server) -> asyncio.Task[None]:
    """Start the minute loop on the server's own event loop.

    Called from ``Server.serve(on_start=...)``, which runs once the
    socket is bound and "announces and returns" — so it may start a task
    but must not wait on one.
    """

    return asyncio.create_task(_loop(server), name="workflows.cron")


def declare(wf: Workflow) -> None:
    """Attach the crontab to ``wf``: five routes and the pane.

    ``ctx`` is named first on every handler for the reason
    :mod:`workflows.feature.files` gives: `mount` falls back to treating
    the first parameter as the context when nothing is annotated.
    """

    @wf.route("/schedules")
    async def schedules_list(ctx: PluginContext) -> dict[str, Any]:
        """Every schedule, and the workflows one may be pointed at."""

        now = datetime.now()
        async with _lock:
            rows = [_view(row, now) for row in _read()]
        known = sorted(_server.workflows) if _server is not None else []
        return {"schedules": rows, "workflows": known, "fields": [f[0] for f in FIELDS]}

    @wf.route("/schedules", methods="POST")
    async def schedules_add(
        ctx: PluginContext, input: dict[str, Any]
    ) -> dict[str, Any]:
        """Add one schedule. The expression is parsed before it is saved."""

        name = str(input.get("workflow", "")).strip()
        cron = " ".join(str(input.get("cron", "")).split())
        title = str(input.get("title", "")).strip()
        prompt = str(input.get("prompt", ""))
        if not name:
            raise PluginError(400, "a schedule needs a workflow to run")
        if _server is not None and name not in _server.workflows:
            raise PluginError(400, f"{name!r} is not a workflow this server runs")
        if not title:
            raise PluginError(400, "a schedule needs a title: it becomes the run's")
        parse(cron)
        row = {
            "id": uuid.uuid4().hex[:12],
            "workflow": name,
            "title": title,
            "prompt": prompt,
            "cron": cron,
            "enabled": True,
            "created": int(time.time()),
        }
        async with _lock:
            rows = _read()
            rows.append(row)
            _write(rows)
        return _view(row, datetime.now())

    @wf.route("/schedules/{schedule_id}", methods="DELETE")
    async def schedules_delete(ctx: PluginContext, schedule_id: str) -> dict[str, Any]:
        """Remove one schedule."""

        async with _lock:
            rows = _read()
            kept = [row for row in rows if row.get("id") != schedule_id]
            if len(kept) == len(rows):
                raise PluginError(404, f"no schedule {schedule_id!r}")
            _write(kept)
        return {"deleted": schedule_id}

    @wf.route("/schedules/{schedule_id}/toggle", methods="POST")
    async def schedules_toggle(ctx: PluginContext, schedule_id: str) -> dict[str, Any]:
        """Turn one schedule on or off without losing it."""

        async with _lock:
            rows = _read()
            for row in rows:
                if row.get("id") == schedule_id:
                    row["enabled"] = not row.get("enabled", True)
                    _write(rows)
                    return _view(row, datetime.now())
        raise PluginError(404, f"no schedule {schedule_id!r}")

    @wf.route("/schedules/{schedule_id}/run", methods="POST")
    async def schedules_run(ctx: PluginContext, schedule_id: str) -> dict[str, Any]:
        """Submit one schedule's run now, without waiting for its minute.

        It does **not** mark the minute as fired: running it by hand is
        the operator asking for one extra run, not a replacement for the
        scheduled one.
        """

        async with _lock:
            rows = _read()
            for row in rows:
                if row.get("id") == schedule_id:
                    run_id = await _fire(
                        row["workflow"],
                        row.get("title") or row["cron"],
                        row.get("prompt", ""),
                    )
                    row["last_run"] = run_id
                    row["last_fired"] = int(time.time())
                    _write(rows)
                    return {"run": run_id}
        raise PluginError(404, f"no schedule {schedule_id!r}")

    wf.panel(
        "cron",
        slot="global",
        kind="custom",
        element="athanore-cron",
    )
