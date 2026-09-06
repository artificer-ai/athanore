"""Importing an MVP database into a v1 one (07 §Importing a v0 database).

The MVP kept six tables in one SQLite file it created in a constructor and
never stamped a revision on. v1 keeps ten, migrated by Alembic, with the
statuses of 03, the event vocabulary of 03 and the payloads of 18.
:func:`import_v0` is the one-way door between them: it reads the MVP file
with :mod:`sqlite3` and writes the destination with Core inserts, applying
07's mapping table row by row.

Four properties are load-bearing, and each is a decision the mapping table
makes rather than something this module invented:

- **The source is never written.** It is opened ``mode=ro`` through a
  SQLite URI, so a bug here cannot damage the database an operator is
  importing *from*; the test hashes the file before and after.
- **A run is the unit.** Each run and everything under it lands in one
  transaction, and a run whose id is already in the destination is
  skipped whole. That is what makes the import idempotent: run it twice
  and the second pass writes nothing.
- **Ids are remapped, except a run's.** 07 keeps ``runs.id`` verbatim —
  the MVP's 32-character uuid hex, not re-minted as a ULID, because
  ordering is by ``position`` anyway. Everything else is integer
  autoincrement in both schemas, so a task, a request or a submission
  gets a fresh id and every reference to it is rewritten through the maps
  built as the rows are written.
- **Nothing is invented.** A column v0 never recorded is left at its
  schema default rather than estimated (`AGENTS.md` §Real data only), and
  the same rule decides which events survive: 18 fixes a required payload
  per event name, so a v0 event whose v1 payload cannot be built from the
  row — ``run_completed`` has no landing task, ``task_status_set`` no
  status to have come *from* — is counted in
  :attr:`ImportReport.dropped_events` instead of being written with
  fabricated fields.

The clear-text task token is the one value deliberately destroyed. 07
gives a *finished* task ``token_hash = sha256(token)`` so the record of
which token claimed it survives, and gives everything else ``NULL``: a
task that could still be claimed is tokened at claim, and a live token
must not survive an import in any form (12 §Task tokens).

``store`` may not import ``athanore.events`` — they are independent
siblings of the bottom tier (02 §Layering) — so the event names here are
string constants, the way ``repos.events`` spells ``run.`` for the
retention exemption. The concrete vocabulary is
``athanore.events.names.EventName`` and :data:`EVENT_NAMES` is checked
against it by the test suite, a tier where both are importable.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple, cast

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from athanore.store.engine import make_engine
from athanore.store.migrate import upgrade
from athanore.store.tables import (
    answers,
    events,
    log_entries,
    requests,
    runs,
    stream_chunks,
    submissions,
    tasks,
)

# --------------------------------------------------------------------------
# The vocabulary this module writes
# --------------------------------------------------------------------------

#: The v1 event names the importer emits, spelled once. Mirrors the
#: members of ``athanore.events.names.EventName`` that a v0 row can carry.
EVENT_NAMES: Mapping[str, str] = {
    "run_created": "run.created",
    "run_updated": "run.updated",
    "run_paused": "run.paused",
    "run_resumed": "run.resumed",
    "run_failed": "run.failed",
    "task_started": "task.started",
    "task_enqueued": "task.enqueued",
    "request_opened": "request.opened",
    "request_answered": "request.answered",
    "submission_repair": "submission.repair",
    "submission_rejected": "submission.rejected",
    "agent_stats": "agent.stats",
}

#: v0 statuses that mean the attempt is over. 07 gives exactly these a
#: ``token_hash``; anything else is still claimable and gets ``NULL``.
FINISHED_TASK_STATUSES: frozenset[str] = frozenset(
    {"done", "failed", "dead_letter", "cancelled"}
)

#: v0 run statuses with no more work to do. Their ``finished`` timestamp
#: is derived below; a live run has none.
FINISHED_RUN_STATUSES: frozenset[str] = frozenset({"completed", "failed", "cancelled"})

#: The MVP's pre-``requests`` message kinds and what its own in-place
#: migration made of them (``Store._migrate_legacy_messages``). ``reply``
#: and ``decision`` become answers; the other two become requests with the
#: ``mode``/``source`` that migration wrote.
LEGACY_REQUEST_KINDS: Mapping[str, tuple[str, str]] = {
    "permission": ("options", "agent"),
    "question": ("text", "node"),
}

#: The legacy kinds that are answers rather than requests.
LEGACY_ANSWER_KINDS: frozenset[str] = frozenset({"decision", "reply"})

#: The prefix a work-log line carries when it is the stats entry of 05.
STATS_PREFIX = "[stats]"

#: The engine's retry line, which 07 maps to ``kind=failure``.
FAILURE_LINE = re.compile(r"^attempt \d+ failed\b")

#: The transcript segment the MVP writes for an ACP ``ToolCallStart``
#: (``"\n\n> tool: <title>\n"``). Everything else it appends is assistant
#: text, so these are the only chunks that are not ``kind=text``.
TOOL_SEGMENT = "> tool:"

#: v1's three log authors (``athanore.store.rows.LogAuthor``). The MVP's
#: task API let an agent send any string, so an unknown one lands on the
#: MVP's own default rather than being written into an enum column.
LOG_AUTHORS: frozenset[str] = frozenset({"agent", "engine", "user"})
DEFAULT_LOG_AUTHOR = "agent"

#: v1's two answer authors (``athanore.store.rows.AnswerAuthor``). Only the
#: engine's headless fallbacks are not a person's.
ANSWER_AUTHORS: frozenset[str] = frozenset({"user", "engine"})
DEFAULT_ANSWER_AUTHOR = "user"

#: v0's repair reasons against 18's. ``missing`` was renamed when the
#: payload was fixed; ``rejected`` was not.
REPAIR_REASONS: Mapping[str, str] = {
    "missing": "nothing_submitted",
    "rejected": "rejected",
}


class ImportReport(NamedTuple):
    """What one import wrote, and what it could not carry.

    Real counts from the statements that ran, never an estimate: a caller
    that prints this is reporting what happened (`AGENTS.md` §Real data
    only). The three ``dropped_*`` fields are the rows v1 has no shape
    for; they are counted rather than passed over in silence, because an
    import that quietly loses history is worse than one that says so.
    """

    #: Runs written, and the tables under them.
    runs: int = 0
    tasks: int = 0
    submissions: int = 0
    log_entries: int = 0
    requests: int = 0
    answers: int = 0
    stream_chunks: int = 0
    events: int = 0
    #: Runs already present in the destination, in the order they were met.
    skipped_runs: tuple[str, ...] = ()
    #: Requests raised against no task: ``requests.task_id`` is NOT NULL.
    dropped_requests: int = 0
    #: Answers with no request to key on (an untargeted legacy ``reply``).
    dropped_answers: int = 0
    #: Events whose v1 payload is not in a v0 row (see the module docstring).
    dropped_events: int = 0


async def import_v0(src: Path, dest_url: str) -> ImportReport:
    """Copy the MVP database at ``src`` into the v1 database ``dest_url``.

    The destination is migrated to head first, so ``src`` may be imported
    into a path that does not exist yet as well as into a database already
    carrying runs. Runs whose id is already there are skipped, which makes
    a second call a no-op.

    ``src`` is opened read-only and is never written.
    """

    source = _open_source(src)
    try:
        await upgrade(dest_url)
        engine = make_engine(dest_url)
        try:
            report = ImportReport()
            for run in _fetch(source, "SELECT * FROM runs ORDER BY priority, created"):
                async with engine.begin() as conn:
                    report = await _import_run(source, conn, run, report)
            # Events naming no run are not imported: the import is keyed
            # on the run id, so an event without one has nothing to be
            # idempotent on and a second pass would duplicate it.
            orphans = _scalar(
                source, "SELECT COUNT(*) FROM events WHERE run_id IS NULL"
            )
            return report._replace(dropped_events=report.dropped_events + orphans)
        finally:
            await engine.dispose()
    finally:
        source.close()


# --------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------


async def _import_run(
    source: sqlite3.Connection,
    conn: AsyncConnection,
    run: sqlite3.Row,
    report: ImportReport,
) -> ImportReport:
    """Write one v0 run and everything under it, or skip it."""

    run_id = str(run["id"])
    present = await conn.execute(select(runs.c.id).where(runs.c.id == run_id))
    if present.first() is not None:
        return report._replace(skipped_runs=(*report.skipped_runs, run_id))

    rows = _run_rows(source, run_id)
    await conn.execute(insert(runs).values(_run_values(run, rows["tasks"])))

    task_ids = await _import_tasks(conn, run_id, rows["tasks"])
    submitted = await _import_submissions(conn, rows["submissions"], task_ids)
    logged = await _import_log(conn, run_id, rows["log"])
    chunks = await _import_stream(conn, rows["events"], task_ids)
    await _apply_stats(conn, rows["events"], task_ids)
    request_ids, dropped_requests = await _import_requests(
        conn, run_id, rows["messages"], task_ids
    )
    answered, dropped_answers = await _import_answers(
        conn, rows["messages"], request_ids
    )
    written, dropped_events = await _import_events(
        conn, run, rows, task_ids, request_ids
    )

    return report._replace(
        runs=report.runs + 1,
        tasks=report.tasks + len(task_ids),
        submissions=report.submissions + submitted,
        log_entries=report.log_entries + logged,
        requests=report.requests + len(request_ids),
        answers=report.answers + answered,
        stream_chunks=report.stream_chunks + chunks,
        events=report.events + written,
        dropped_requests=report.dropped_requests + dropped_requests,
        dropped_answers=report.dropped_answers + dropped_answers,
        dropped_events=report.dropped_events + dropped_events,
    )


def _run_rows(source: sqlite3.Connection, run_id: str) -> dict[str, list[sqlite3.Row]]:
    """Every v0 row belonging to ``run_id``, in id order per table."""

    task_rows = _fetch(
        source, "SELECT * FROM tasks WHERE run_id = ? ORDER BY id", (run_id,)
    )
    task_ids = [int(row["id"]) for row in task_rows]
    placeholders = ", ".join("?" for _ in task_ids)
    submission_rows: list[sqlite3.Row] = []
    if task_ids:
        submission_rows = _fetch(
            source,
            f"SELECT * FROM submissions WHERE task_id IN ({placeholders}) ORDER BY id",
            tuple(task_ids),
        )
    return {
        "tasks": task_rows,
        "submissions": submission_rows,
        "log": _fetch(
            source, "SELECT * FROM log WHERE run_id = ? ORDER BY id", (run_id,)
        ),
        "messages": _fetch(
            source, "SELECT * FROM messages WHERE run_id = ? ORDER BY id", (run_id,)
        ),
        "events": _fetch(
            source, "SELECT * FROM events WHERE run_id = ? ORDER BY id", (run_id,)
        ),
    }


def _run_values(run: sqlite3.Row, task_rows: list[sqlite3.Row]) -> dict[str, Any]:
    """The ``runs`` row for one v0 run.

    Two mappings 07 names: ``priority`` becomes ``position``, and a
    ``running`` run that never started a task becomes ``queued`` — v1's
    new status for "exists, has dispatched nothing", which is what such a
    run actually is.

    ``finished`` has no v0 column. A finished run takes the last real
    timestamp its own rows carry — the latest ``tasks.finished``, or
    ``runs.updated`` when nothing under it ever finished, which is the
    write that set the terminal status — and a live run takes ``NULL``.
    """

    status = str(run["status"])
    started = [row for row in task_rows if row["started"] is not None]
    if status == "running" and not started:
        status = "queued"

    finished: float | None = None
    if status in FINISHED_RUN_STATUSES:
        stamps = [
            float(row["finished"]) for row in task_rows if row["finished"] is not None
        ]
        finished = max(stamps) if stamps else float(run["updated"])

    return {
        "id": str(run["id"]),
        "workflow": str(run["workflow"]),
        "status": status,
        "title": run["title"] or "",
        "description": run["description"] or "",
        "output": _json(run["output"]),
        "position": int(run["priority"] or 0),
        "created": _stamp(run["created"]),
        "updated": _stamp(run["updated"]),
        "finished": None if finished is None else _stamp(finished),
    }


async def _import_tasks(
    conn: AsyncConnection, run_id: str, task_rows: list[sqlite3.Row]
) -> dict[int, int]:
    """Write the run's tasks and return ``{v0 id: v1 id}``.

    ``run_priority`` is dropped (04 gave the ordering to the joined run's
    ``position``), the clear-text ``token`` becomes a hash or nothing, and
    the columns v0 never had — ``stats``, ``lineage``, ``terminal``,
    ``branch`` — take their schema defaults. ``stats`` is filled in
    afterwards from the ``run_stats`` events.
    """

    mapping: dict[int, int] = {}
    for row in task_rows:
        status = str(row["status"])
        token = row["token"]
        token_hash = (
            _sha256(str(token))
            if token is not None and status in FINISHED_TASK_STATUSES
            else None
        )
        result = await conn.execute(
            insert(tasks)
            .values(
                run_id=run_id,
                node=str(row["node"]),
                attempt=int(row["attempt"]),
                status=status,
                payload=_json(row["payload"]),
                result=_json(row["result"]),
                error=row["error"],
                priority=int(row["priority"] or 0),
                explicit=bool(row["explicit"]),
                token_hash=token_hash,
                terminal=False,
                branch=[],
                created=_stamp(row["created"]),
                started=_stamp(row["started"]),
                finished=_stamp(row["finished"]),
            )
            .returning(tasks.c.id)
        )
        mapping[int(row["id"])] = int(result.scalar_one())
    return mapping


async def _import_submissions(
    conn: AsyncConnection, rows: list[sqlite3.Row], task_ids: Mapping[int, int]
) -> int:
    """Copy the submissions of the run's tasks. The shape is unchanged."""

    values = [
        {
            "task_id": task_ids[int(row["task_id"])],
            "payload": _json(row["payload"]),
            "created": _stamp(row["created"]),
        }
        for row in rows
        if int(row["task_id"]) in task_ids
    ]
    if values:
        await conn.execute(insert(submissions), values)
    return len(values)


async def _import_log(
    conn: AsyncConnection, run_id: str, rows: list[sqlite3.Row]
) -> int:
    """Copy the work log, inferring the ``kind`` v1 added.

    07 names two: a line beginning ``[stats]`` is the stats entry, and the
    engine's ``attempt N failed`` line is a failure. Everything else is a
    plain entry, whose ``kind`` is ``NULL`` rather than guessed at.
    ``log_entries.task_id`` stays ``NULL`` throughout: the MVP's ``log``
    table has no task column.
    """

    values: list[dict[str, Any]] = []
    for row in rows:
        author = str(row["author"])
        if author not in LOG_AUTHORS:
            author = DEFAULT_LOG_AUTHOR
        values.append(
            {
                "run_id": run_id,
                "task_id": None,
                "node": str(row["node"]),
                "author": author,
                "kind": _log_kind(author, str(row["text"])),
                "text": str(row["text"]),
                "created": _stamp(row["created"]),
            }
        )
    if values:
        await conn.execute(insert(log_entries), values)
    return len(values)


def _log_kind(author: str, text: str) -> str | None:
    """The ``kind`` 07 infers for a v0 log line, or ``None``."""

    if text.startswith(STATS_PREFIX):
        return "stats"
    if author == "engine" and FAILURE_LINE.match(text):
        return "failure"
    return None


async def _import_stream(
    conn: AsyncConnection, event_rows: list[sqlite3.Row], task_ids: Mapping[int, int]
) -> int:
    """Turn the ``agent_progress`` events into the transcript.

    One chunk per appended segment, numbered from 1 per task in event
    order, which is the order the flusher wrote them. A segment the MVP
    produced for a tool call is ``kind=tool_call`` and everything else is
    ``kind=text`` (07).
    """

    values: list[dict[str, Any]] = []
    seq: dict[int, int] = {}
    for row in event_rows:
        if str(row["kind"]) != "agent_progress" or row["task_id"] is None:
            continue
        task_id = task_ids.get(int(row["task_id"]))
        if task_id is None:
            continue
        segments = _json_object(row["data"]).get("append")
        if not isinstance(segments, list):
            continue
        stamp = _stamp(row["created"])
        for segment in cast("list[Any]", segments):
            text = str(segment)
            seq[task_id] = seq.get(task_id, 0) + 1
            values.append(
                {
                    "task_id": task_id,
                    "seq": seq[task_id],
                    "kind": "tool_call" if TOOL_SEGMENT in text else "text",
                    "text": text,
                    "created": stamp,
                }
            )
    if values:
        await conn.execute(insert(stream_chunks), values)
    return len(values)


async def _apply_stats(
    conn: AsyncConnection, event_rows: list[sqlite3.Row], task_ids: Mapping[int, int]
) -> None:
    """Write ``tasks.stats`` from the ``run_stats`` events.

    07 sends a ``run_stats`` event to two places: the ``agent.stats``
    event, written with the rest of the events, and the stats column of
    the task it names, so a run's totals are one aggregate rather than an
    event scan. A ``run_stats`` that names no task still becomes the
    event — its data is the whole payload (18) — and simply fills no
    column.
    """

    for row in event_rows:
        if str(row["kind"]) != "run_stats" or row["task_id"] is None:
            continue
        task_id = task_ids.get(int(row["task_id"]))
        stats = _json_object(row["data"])
        if task_id is None or not stats:
            continue
        await conn.execute(
            tasks.update().where(tasks.c.id == task_id).values(stats=stats)
        )


# --------------------------------------------------------------------------
# The request channel
# --------------------------------------------------------------------------


async def _import_requests(
    conn: AsyncConnection,
    run_id: str,
    rows: list[sqlite3.Row],
    task_ids: Mapping[int, int],
) -> tuple[dict[int, int], int]:
    """Write the ``request`` messages and return ``{v0 id: v1 id}``.

    ``mode`` and ``source`` come from the message's ``data``, as they did
    in the MVP; the pre-``requests`` ``permission`` and ``question`` kinds
    get the pair its own in-place migration gave them. ``kind`` is v1's
    addition: the MVP wrote one into ``data`` from the moment the channel
    had three of them, and a row from before that is classified the way
    the MVP itself raised them — an agent asking with options is a
    permission, an agent asking for an object is an elicitation, and a
    node asking anything is a question.

    ``ordinal`` stays ``NULL``. It numbers the node-raised requests of one
    task so a re-executing body re-attaches (06 §Restart durability), and
    v0 recorded no such number; inventing one would claim an ordering the
    source never had.
    """

    mapping: dict[int, int] = {}
    dropped = 0
    for row in rows:
        shape = _request_shape(row)
        if shape is None:
            continue
        mode, source, data = shape
        v0_task = row["task_id"]
        task_id = task_ids.get(int(v0_task)) if v0_task is not None else None
        if task_id is None:
            # `requests.task_id` is NOT NULL in v1: a request is asked by
            # an attempt, and one that names no task cannot be attributed.
            dropped += 1
            continue
        result = await conn.execute(
            insert(requests)
            .values(
                run_id=run_id,
                task_id=task_id,
                ordinal=None,
                prompt=str(row["text"]),
                mode=mode,
                source=source,
                kind=_request_kind(mode, source, data),
                options=data.get("options"),
                schema=data.get("schema"),
                tool_call=data.get("tool_call"),
                created=_stamp(row["created"]),
            )
            .returning(requests.c.id)
        )
        mapping[int(row["id"])] = int(result.scalar_one())
    return mapping, dropped


def _request_shape(row: sqlite3.Row) -> tuple[str, str, dict[str, Any]] | None:
    """``(mode, source, data)`` if ``row`` is a request, else ``None``."""

    kind = str(row["kind"])
    data = _json_object(row["data"])
    if kind == "request":
        return str(data.get("mode") or "text"), str(data.get("source") or "node"), data
    legacy = LEGACY_REQUEST_KINDS.get(kind)
    if legacy is None:
        return None
    mode, source = legacy
    return str(data.get("mode") or mode), str(data.get("source") or source), data


def _request_kind(mode: str, source: str, data: Mapping[str, Any]) -> str:
    """v1's ``RequestKind`` for a v0 request."""

    declared = data.get("kind")
    if isinstance(declared, str) and declared:
        return declared
    if source == "agent":
        return "permission" if mode == "options" else "elicitation"
    return "question"


async def _import_answers(
    conn: AsyncConnection, rows: list[sqlite3.Row], request_ids: Mapping[int, int]
) -> tuple[int, int]:
    """Write the ``answer`` messages, keyed by the request they answer.

    ``answers`` has no id of its own: the primary key is the request, so
    an answer whose ``ref`` names no imported request has nowhere to go.
    That is the untargeted legacy ``reply`` the MVP's own migration left
    alone — history, and nothing ever claimed it — and it is counted, not
    written.
    """

    written = 0
    dropped = 0
    for row in rows:
        kind = str(row["kind"])
        if kind != "answer" and kind not in LEGACY_ANSWER_KINDS:
            continue
        ref = row["ref"]
        request_id = request_ids.get(int(ref)) if ref is not None else None
        if request_id is None:
            dropped += 1
            continue
        data = _json_object(row["data"])
        author = str(row["author"])
        if author not in ANSWER_AUTHORS:
            author = DEFAULT_ANSWER_AUTHOR
        option_id = data.get("option_id")
        value = data.get("value")
        if option_id is None and value is None:
            # A `reply` the MVP would have rewritten to `{"value": text}`
            # on its next open (`_migrate_legacy_messages`).
            value = str(row["text"])
        await conn.execute(
            insert(answers).values(
                request_id=request_id,
                author=author,
                option_id=None if option_id is None else str(option_id),
                value=value,
                consumed=bool(row["consumed"]),
                created=_stamp(row["created"]),
            )
        )
        written += 1
    return written, dropped


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------


async def _import_events(
    conn: AsyncConnection,
    run: sqlite3.Row,
    rows: Mapping[str, list[sqlite3.Row]],
    task_ids: Mapping[int, int],
    request_ids: Mapping[int, int],
) -> tuple[int, int]:
    """Rename the run's events onto 03's vocabulary and write them.

    ``agent_progress`` and ``run_stats`` are the two that also went
    somewhere else: the first *becomes* the transcript and is not an event
    in v1 at all, the second keeps its data verbatim under ``agent.stats``
    (18) as well as filling ``tasks.stats``.

    Everything else is a rename plus a payload rebuilt to 18's shape, and
    a kind whose required fields are not in a v0 row is dropped rather
    than written with invented ones.
    """

    by_id = {int(row["id"]): row for row in rows["tasks"]}
    values: list[dict[str, Any]] = []
    dropped = 0
    for row in rows["events"]:
        kind = str(row["kind"])
        if kind == "agent_progress":
            continue
        v0_task = row["task_id"]
        task_id = task_ids.get(int(v0_task)) if v0_task is not None else None
        task = by_id.get(int(v0_task)) if v0_task is not None else None
        mapped = _event_payload(
            kind, _json_object(row["data"]), run, task, task_id, request_ids
        )
        if mapped is None:
            dropped += 1
            continue
        name, data = mapped
        values.append(
            {
                "run_id": str(run["id"]),
                "task_id": task_id,
                "name": name,
                "data": data,
                "created": _stamp(row["created"]),
            }
        )
    if values:
        await conn.execute(insert(events), values)
    return len(values), dropped


def _event_payload(
    kind: str,
    data: dict[str, Any],
    run: sqlite3.Row,
    task: sqlite3.Row | None,
    task_id: int | None,
    request_ids: Mapping[int, int],
) -> tuple[str, dict[str, Any]] | None:
    """``(name, data)`` for one v0 event, or ``None`` if v1 cannot hold it.

    The kinds that return ``None`` are the ones 18 gives a required field
    the MVP never recorded: ``run_completed`` (the landing task, the
    output, the terminal branches), ``run_cancelled`` (which tasks were
    cancelled), ``run_reordered`` and ``run_priority_set`` (the position
    it moved *from*), ``task_moved`` (the new task), ``task_status_set``
    (the status it left), ``submission`` (the row that was accepted) and
    ``log`` (the entry that was appended).
    """

    if kind == "run_stats":
        # 18: "the stats entry of 05 §Stats entry verbatim".
        return EVENT_NAMES["agent_stats"], dict(data)

    if kind == "run_created":
        return EVENT_NAMES["run_created"], {
            "workflow": str(run["workflow"]),
            "title": run["title"] or "",
            "position": int(run["priority"] or 0),
        }

    if kind == "run_updated":
        changed = {
            field: data[field]
            for field in ("title", "description")
            if isinstance(data.get(field), str)
        }
        return EVENT_NAMES["run_updated"], {"changed": changed}

    if kind == "run_paused":
        return EVENT_NAMES["run_paused"], {}

    if kind == "run_resumed":
        return EVENT_NAMES["run_resumed"], {}

    if kind == "run_failed":
        node = data.get("node")
        error = data.get("error")
        if task_id is None or not isinstance(node, str) or not isinstance(error, str):
            return None
        return EVENT_NAMES["run_failed"], {
            "node": node,
            "task_id": task_id,
            "error": error,
        }

    if kind == "task_started":
        if task is None:
            return None
        return EVENT_NAMES["task_started"], {
            "node": str(task["node"]),
            "attempt": int(task["attempt"]),
        }

    if kind in _ENQUEUE_REASONS:
        if task is None:
            return None
        return EVENT_NAMES["task_enqueued"], {
            "node": str(task["node"]),
            "attempt": int(task["attempt"]),
            "reason": _ENQUEUE_REASONS[kind],
            "payload_present": task["payload"] is not None,
            "branch": [],
        }

    if kind == "request_opened":
        request_id = _mapped_request(data, request_ids)
        mode = data.get("mode")
        source = data.get("source")
        if (
            request_id is None
            or task is None
            or not isinstance(mode, str)
            or not isinstance(source, str)
        ):
            return None
        return EVENT_NAMES["request_opened"], {
            "request_id": request_id,
            "mode": mode,
            "kind": _request_kind(mode, source, data),
            "source": source,
            "node": str(task["node"]),
        }

    if kind == "request_answered":
        request_id = _mapped_request(data, request_ids)
        if request_id is None:
            return None
        author = data.get("author")
        payload: dict[str, Any] = {
            "request_id": request_id,
            "author": author if author in ANSWER_AUTHORS else DEFAULT_ANSWER_AUTHOR,
        }
        option_id = data.get("option_id")
        if isinstance(option_id, str):
            payload["option_id"] = option_id
        return EVENT_NAMES["request_answered"], payload

    if kind == "submission_repair":
        reason = REPAIR_REASONS.get(str(data.get("reason")))
        turn = data.get("turn")
        if task is None or reason is None or not isinstance(turn, int):
            return None
        return EVENT_NAMES["submission_repair"], {
            "node": str(task["node"]),
            "turn": turn,
            "reason": reason,
        }

    if kind == "submission_rejected":
        errors = data.get("errors")
        if task is None or not isinstance(errors, list):
            return None
        # 18: the payload itself is never in the event.
        return EVENT_NAMES["submission_rejected"], {
            "node": str(task["node"]),
            "errors": cast("list[Any]", errors),
        }

    return None


#: The v0 kinds that are all one v1 event, distinguished by ``reason``:
#: 03 folded the MVP's transition and its three re-enqueue notices into
#: ``task.enqueued``.
_ENQUEUE_REASONS: Mapping[str, str] = {
    "transition": "transition",
    "task_retry": "retry",
    "task_rerun": "rerun",
    "task_manual_retry": "manual_retry",
}


def _mapped_request(
    data: Mapping[str, Any], request_ids: Mapping[int, int]
) -> int | None:
    """The v1 id of the request an event names, if it was imported."""

    request_id = data.get("request_id")
    if not isinstance(request_id, int):
        return None
    return request_ids.get(request_id)


# --------------------------------------------------------------------------
# Reading the source
# --------------------------------------------------------------------------


def _open_source(src: Path) -> sqlite3.Connection:
    """Open ``src`` read-only, or say why it is not a v0 database."""

    path = Path(src)
    if not path.exists():
        raise FileNotFoundError(f"no v0 database at {path}")
    # `mode=ro` rather than a promise not to write: the source is somebody
    # else's database and SQLite is the only thing that can enforce it.
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        names = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        missing = {"runs", "tasks", "log", "messages", "events"} - names
        if missing:
            raise ValueError(
                f"{path} is not a v0 athanore database: "
                f"missing {', '.join(sorted(missing))}"
            )
    except BaseException:
        conn.close()
        raise
    return conn


def _fetch(
    conn: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()
) -> list[sqlite3.Row]:
    """Every row ``sql`` selects."""

    return list(conn.execute(sql, params))


def _scalar(conn: sqlite3.Connection, sql: str) -> int:
    """The first column of the first row of ``sql``, as an int."""

    row = conn.execute(sql).fetchone()
    return 0 if row is None else int(row[0])


def _json(value: Any) -> Any:
    """A v0 JSON text column as a Python value.

    The MVP wrote these with ``json.dumps(..., default=str)`` and read
    them back leniently, so a column that is not JSON is kept as the text
    it is rather than discarded.
    """

    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _json_object(value: Any) -> dict[str, Any]:
    """A v0 JSON text column as an object, or ``{}`` if it is not one.

    Every ``data`` column the mapping reads is a JSON object where it is
    anything at all, and a row that predates a field simply has fewer
    keys; a column holding something else is a row nothing can be read
    out of, which is the same thing as an empty one here.
    """

    parsed: object = _json(value)
    if not isinstance(parsed, dict):
        return {}
    return cast("dict[str, Any]", parsed)


def _stamp(value: Any) -> datetime | None:
    """A v0 epoch-seconds timestamp as an aware UTC datetime."""

    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


def _sha256(token: str) -> str:
    """The hash 07 keeps in place of a finished task's token."""

    return hashlib.sha256(token.encode()).hexdigest()


__all__ = [
    "EVENT_NAMES",
    "FINISHED_RUN_STATUSES",
    "FINISHED_TASK_STATUSES",
    "ImportReport",
    "import_v0",
]
