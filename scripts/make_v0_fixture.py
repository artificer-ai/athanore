#!/usr/bin/env python
"""Write the committed v0 database the importer is tested against.

`tests/fixtures/v0/mvp_small.sqlite3` is a small but complete MVP
database: two runs, tasks in every v0 status, a work log carrying both
inferred kinds, the request/answer channel including the pre-`requests`
kinds, and the three event kinds 07 §Importing a v0 database maps.
`athanore.store.legacy.import_v0` turns it into a v1 database and
`tests/store/test_legacy_import.py` counts what came out.

**The schema is transcribed, not imported.** T018 says to build this with
the MVP's own ``athanore.store.Store``, and that class is not here: D65
removed the MVP code from this repository and D67 forbids v0 and v1
sharing an environment, so importing v0's ``athanore`` package to write a
test fixture is exactly the collision that decision exists to prevent
(D91). :data:`V0_SCHEMA` below is therefore the DDL of the sibling
checkout's ``athanore/store.py`` — the ``_SCHEMA`` script *after* the
``ALTER TABLE`` upgrades its constructor applies, which is the shape any
database that has been opened by a current MVP has.

Everything is written with fixed ids and fixed epoch timestamps, so the
file is a constant: re-running this script on the same source produces
the same rows, and a diff on the fixture means somebody changed the
fixture.

Run it from the checkout:

    ./scripts/dev.sh "uv run scripts/make_v0_fixture.py"
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "v0" / "mvp_small.sqlite3"

#: The MVP's schema as a current MVP leaves it: `_SCHEMA` from the
#: sibling checkout's `athanore/store.py`, with `tasks.run_priority` and
#: the `messages` permission-channel columns (`task_id`, `ref`, `data`)
#: that its constructor adds by `ALTER TABLE` folded in.
V0_SCHEMA = """
CREATE TABLE runs(
    id TEXT PRIMARY KEY,
    workflow TEXT NOT NULL,
    status TEXT NOT NULL,
    title TEXT,
    description TEXT,
    output TEXT,
    created REAL NOT NULL,
    updated REAL NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE tasks(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    node TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    payload TEXT,
    result TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    explicit INTEGER NOT NULL DEFAULT 0,
    token TEXT NOT NULL,
    created REAL NOT NULL,
    started REAL,
    finished REAL,
    error TEXT,
    run_priority INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE submissions(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    payload TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE events(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT,
    task_id INTEGER,
    kind TEXT NOT NULL,
    data TEXT,
    created REAL NOT NULL
);
CREATE TABLE log(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    node TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'agent',
    text TEXT NOT NULL,
    created REAL NOT NULL
);
CREATE TABLE messages(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT 'user',
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    consumed INTEGER NOT NULL DEFAULT 0,
    created REAL NOT NULL,
    task_id INTEGER,
    ref INTEGER,
    data TEXT
);
CREATE INDEX idx_tasks_ready ON tasks(status, priority, created);
CREATE INDEX idx_log ON log(run_id);
CREATE INDEX idx_messages ON messages(run_id);
"""

# The MVP mints run ids as `uuid4().hex[:12]`; these two are fixed so the
# fixture is reproducible and the test can name them.
DONE_RUN = "0a1b2c3d4e5f"
QUEUED_RUN = "1a2b3c4d5e6f"

# 2026-03-01T12:00:00Z, and one second per step after it. The MVP stores
# epoch seconds as REAL.
T0 = 1772366400.0


def t(step: float) -> float:
    """``step`` seconds after the fixture's epoch."""
    return T0 + step


def dumps(obj: Any) -> str:
    """The MVP's JSON encoding for a text column."""
    return json.dumps(obj, default=str)


RUNS: list[tuple[Any, ...]] = [
    # A finished run: it has the transcript, the stats and the requests.
    (
        DONE_RUN,
        "v1_feature",
        "completed",
        "T017 retention",
        "Add the retention job.",
        dumps({"merged": True}),
        t(0),
        t(600),
        0,
    ),
    # `running`, but nothing was ever started: 07 maps this to `queued`.
    (
        QUEUED_RUN,
        "v1_feature",
        "running",
        "T018 v0 importer",
        "Port the MVP database.",
        None,
        t(10),
        t(10),
        1,
    ),
]

# id, run_id, node, attempt, status, payload, result, priority, explicit,
# token, created, started, finished, error, run_priority.
TASKS: list[tuple[Any, ...]] = [
    (
        1,
        DONE_RUN,
        "plan",
        1,
        "done",
        dumps({"title": "T017 retention"}),
        dumps({"steps": 3}),
        0,
        0,
        "tok-plan-1",
        t(0),
        t(1),
        t(150),
        None,
        0,
    ),
    (
        2,
        DONE_RUN,
        "build",
        1,
        "failed",
        dumps({"steps": 3}),
        None,
        0,
        0,
        "tok-build-1",
        t(150),
        t(151),
        t(200),
        "boom",
        0,
    ),
    (
        3,
        DONE_RUN,
        "build",
        2,
        "dead_letter",
        dumps({"steps": 3}),
        None,
        0,
        0,
        "tok-build-2",
        t(150),
        t(201),
        t(260),
        "boom again",
        0,
    ),
    (
        4,
        DONE_RUN,
        "review",
        1,
        "cancelled",
        dumps({"steps": 3}),
        None,
        0,
        0,
        "tok-review-1",
        t(260),
        t(261),
        t(300),
        None,
        0,
    ),
    # An attempt the MVP was still running when the process died: the
    # importer must not carry its live token over.
    (
        5,
        DONE_RUN,
        "qa",
        1,
        "in_progress",
        dumps({"steps": 3}),
        None,
        5,
        1,
        "tok-qa-1",
        t(300),
        t(301),
        None,
        None,
        0,
    ),
    # The queued run's only task: enqueued, never claimed, never started.
    (
        6,
        QUEUED_RUN,
        "prepare",
        1,
        "ready",
        dumps({"title": "T018"}),
        None,
        0,
        0,
        "tok-prepare-1",
        t(10),
        None,
        None,
        None,
        1,
    ),
]

# id, task_id, payload, created.
SUBMISSIONS: list[tuple[Any, ...]] = [
    (1, 1, dumps({"steps": 3}), t(140)),
    (2, 2, dumps({"branch": "feat/T017"}), t(190)),
]

# id, run_id, node, author, text, created. Two of these carry a kind the
# importer infers: the `[stats]` line and the engine's failure line.
LOG: list[tuple[Any, ...]] = [
    (1, DONE_RUN, "plan", "agent", "Planned three steps.", t(150)),
    (
        2,
        DONE_RUN,
        "plan",
        "engine",
        "[stats] node=plan attempt=1 ok — model=openrouter/qwen3-coder,"
        " tokens=12,406 in / 1,204 out / 13,610 total, tools=3 calls,"
        " cost=$0.0120, 149s, session=01a01646",
        t(150),
    ),
    (3, DONE_RUN, "build", "engine", "attempt 1 failed: boom", t(200)),
    (4, DONE_RUN, "review", "user", "Looks right to me.", t(300)),
    # An author the task API let an agent invent (`body.get("author",
    # "agent")`): v1's LogAuthor has three members, so it lands on the
    # MVP's own default.
    (5, DONE_RUN, "qa", "builder-7", "Started the QA pass.", t(310)),
    (6, QUEUED_RUN, "prepare", "user", "Queued behind T017.", t(10)),
]

_PERMISSION_OPTIONS = [
    {"option_id": "allow_once", "name": "Allow once", "kind": "allow_once"},
    {"option_id": "reject_once", "name": "Reject", "kind": "reject_once"},
]

# id, run_id, author, kind, text, consumed, created, task_id, ref, data.
MESSAGES: list[tuple[Any, ...]] = [
    # A node-raised options request and the answer that was claimed.
    (
        1,
        DONE_RUN,
        "node",
        "request",
        "Which approach?",
        0,
        t(20),
        1,
        None,
        dumps(
            {
                "mode": "options",
                "source": "node",
                "kind": "question",
                "options": [
                    {"option_id": "small", "name": "Smallest change"},
                    {"option_id": "full", "name": "Full rewrite"},
                ],
            }
        ),
    ),
    (
        2,
        DONE_RUN,
        "user",
        "answer",
        "small",
        1,
        t(30),
        1,
        1,
        dumps({"option_id": "small"}),
    ),
    # The pre-`requests` kinds, exactly as an un-migrated MVP database
    # holds them: `permission` and `question` are requests, `decision` and
    # a `reply` carrying a `ref` are answers.
    (
        3,
        DONE_RUN,
        "agent",
        "permission",
        "permission: write file",
        0,
        t(160),
        2,
        None,
        dumps({"options": _PERMISSION_OPTIONS, "tool_call": {"title": "write"}}),
    ),
    (
        4,
        DONE_RUN,
        "user",
        "decision",
        "allow_once",
        1,
        t(165),
        2,
        3,
        dumps({"option_id": "allow_once"}),
    ),
    (5, DONE_RUN, "node", "question", "Proceed?", 0, t(170), 2, None, None),
    (6, DONE_RUN, "user", "reply", "yes, proceed", 0, t(175), 2, 5, None),
    # An agent-raised elicitation that nobody answered before the attempt
    # died: v1 shows it stale rather than pending.
    (
        7,
        DONE_RUN,
        "agent",
        "request",
        "the agent has a question",
        0,
        t(305),
        5,
        None,
        dumps(
            {
                "mode": "form",
                "source": "agent",
                "kind": "elicitation",
                "schema": {"type": "object", "properties": {"why": {"type": "string"}}},
            }
        ),
    ),
    # A request the MVP raised with no task (`create_request` takes
    # `task_id=None`). v1's `requests.task_id` is NOT NULL, so this one
    # has nowhere to go and the report counts it.
    (
        8,
        DONE_RUN,
        "node",
        "request",
        "Anything else?",
        0,
        t(320),
        None,
        None,
        dumps({"mode": "text", "source": "node"}),
    ),
    # An untargeted legacy reply: the MVP's own migration leaves it alone
    # (history, nothing claims it) and v1 keys an answer on its request.
    (9, DONE_RUN, "user", "reply", "noted", 0, t(330), None, None, None),
]

_STATS = {
    "node": "plan",
    "attempt": 1,
    "status": "ok",
    "model": "openrouter/qwen3-coder",
    "input_tokens": 12406,
    "output_tokens": 1204,
    "total_tokens": 13610,
    "tool_calls": 3,
    "cost": 0.012,
    "duration_s": 149,
    "session_id": "01a01646",
}

# id, run_id, task_id, kind, data, created.
EVENTS: list[tuple[Any, ...]] = [
    (
        1,
        DONE_RUN,
        1,
        "run_created",
        dumps(
            {
                "workflow": "v1_feature",
                "title": "T017 retention",
                "description": "Add the retention job.",
            }
        ),
        t(0),
    ),
    (2, DONE_RUN, 1, "task_started", dumps({"node": "plan", "attempt": 1}), t(1)),
    # The transcript, in two flushes, with a tool line in the middle.
    (
        3,
        DONE_RUN,
        1,
        "agent_progress",
        dumps(
            {
                "append": [
                    "Reading the plan.",
                    "\n\n> tool: read docs/v1/17-serial-task-plan.md\n",
                    " Three steps, then the gate.",
                ]
            }
        ),
        t(60),
    ),
    (
        4,
        DONE_RUN,
        1,
        "agent_progress",
        dumps(
            {
                "append": [
                    "\n\n> tool: write athanore/store/retention.py\n",
                    "Done.",
                ]
            }
        ),
        t(120),
    ),
    (5, DONE_RUN, 1, "run_stats", dumps(_STATS), t(150)),
    (6, DONE_RUN, 2, "transition", dumps({"from": "plan", "to": "build"}), t(150)),
    (
        7,
        DONE_RUN,
        2,
        "request_opened",
        dumps(
            {
                "request_id": 3,
                "mode": "options",
                "source": "agent",
                "prompt": "permission: write file",
            }
        ),
        t(160),
    ),
    (
        8,
        DONE_RUN,
        2,
        "request_answered",
        dumps({"request_id": 3, "author": "user", "option_id": "allow_once"}),
        t(165),
    ),
    (
        9,
        DONE_RUN,
        2,
        "submission_repair",
        dumps({"turn": 1, "reason": "missing", "errors": None}),
        t(180),
    ),
    (
        10,
        DONE_RUN,
        2,
        "submission_rejected",
        dumps(
            {
                "payload": {"branch": None},
                "errors": [{"loc": ["branch"], "msg": "expected str", "type": "type"}],
            },
        ),
        t(185),
    ),
    (
        11,
        DONE_RUN,
        3,
        "task_retry",
        dumps({"node": "build", "attempt": 2, "error": "boom"}),
        t(201),
    ),
    (
        12,
        DONE_RUN,
        3,
        "run_failed",
        dumps({"node": "build", "error": "boom again"}),
        t(260),
    ),
    (13, DONE_RUN, 4, "task_rerun", dumps({"node": "review"}), t(261)),
    (14, DONE_RUN, 5, "task_manual_retry", dumps({"node": "qa", "attempt": 1}), t(301)),
    (15, DONE_RUN, None, "run_paused", dumps({"note": "waiting on review"}), t(400)),
    (16, DONE_RUN, None, "run_resumed", dumps({}), t(410)),
    (17, DONE_RUN, None, "run_updated", dumps({"title": "T017 retention"}), t(420)),
    # Kinds v1 cannot carry: `run.completed` wants the landing task and
    # the terminal branches, `run.reordered` the position it came from,
    # `task.status_set` the status it left, `submission.accepted` the row
    # it accepted, `log.appended` the entry it appended. None of that is
    # in a v0 row, so the importer counts them instead of inventing them.
    (18, DONE_RUN, None, "run_completed", dumps({}), t(600)),
    (19, DONE_RUN, None, "run_reordered", dumps({"direction": "up"}), t(430)),
    (20, DONE_RUN, 4, "task_status_set", dumps({"status": "cancelled"}), t(300)),
    (21, DONE_RUN, 1, "submission", dumps({"steps": 3}), t(140)),
    (22, DONE_RUN, 1, "log", dumps({"text": "Planned three steps."}), t(150)),
    # No run: the import is keyed on the run, so an event that names none
    # has nothing to be idempotent on.
    (23, None, None, "recovered", dumps({"tasks": [5]}), t(500)),
    (
        24,
        QUEUED_RUN,
        None,
        "run_created",
        dumps(
            {
                "workflow": "v1_feature",
                "title": "T018 v0 importer",
                "description": "Port the MVP database.",
            }
        ),
        t(10),
    ),
]


def build(path: Path) -> None:
    """Write the fixture at ``path``, replacing whatever was there."""

    for stale in (
        path,
        path.with_name(path.name + "-wal"),
        path.with_name(path.name + "-shm"),
    ):
        stale.unlink(missing_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        with conn:
            conn.executescript(V0_SCHEMA)
            conn.executemany(
                "INSERT INTO runs(id, workflow, status, title, description,"
                " output, created, updated, priority)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                RUNS,
            )
            conn.executemany(
                "INSERT INTO tasks(id, run_id, node, attempt, status, payload,"
                " result, priority, explicit, token, created, started,"
                " finished, error, run_priority)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                TASKS,
            )
            conn.executemany(
                "INSERT INTO submissions(id, task_id, payload, created)"
                " VALUES (?, ?, ?, ?)",
                SUBMISSIONS,
            )
            conn.executemany(
                "INSERT INTO log(id, run_id, node, author, text, created)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                LOG,
            )
            conn.executemany(
                "INSERT INTO messages(id, run_id, author, kind, text, consumed,"
                " created, task_id, ref, data)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                MESSAGES,
            )
            conn.executemany(
                "INSERT INTO events(id, run_id, task_id, kind, data, created)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                EVENTS,
            )
        # The MVP runs in WAL; a fixture is read-only and must be one
        # file, so it is checkpointed back to a rollback journal.
        conn.execute("VACUUM")
    finally:
        conn.close()


def main() -> None:
    build(FIXTURE)
    print(f"wrote {FIXTURE.relative_to(ROOT)} ({FIXTURE.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
