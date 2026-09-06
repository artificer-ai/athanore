"""The schema of 07 §Schema as SQLAlchemy 2.0 Core ``Table`` objects.

There is no ORM in this build: a repository reads Core ``Row``s and hands
out the frozen read models of :mod:`athanore.store.rows`, so this module
is the only description of the database's shape. It is also what Alembic
autogenerates the first migration against (T012), which is why the
``MetaData`` carries a naming convention — an unnamed constraint gets a
name from the backend otherwise, and a name that differs between SQLite
and PostgreSQL is a migration that cannot be written once.

Conventions used here:

- ``String`` for identifiers and the enum-ish values (a status, a node
  name, an event name), ``Text`` for unbounded prose (an error, a log
  line, a transcript chunk, a request prompt). Neither carries a length
  except ``tasks.token_hash``, which 07 fixes at ``CHAR(64)``: run ids are
  ULIDs today but a v0 import keeps the MVP's 32-character uuid hex
  verbatim (07 §Importing a v0 database), so a length on an id column
  would reject the rows the importer is required to carry over.
- A column is ``NOT NULL`` exactly where its read model in
  :mod:`athanore.store.rows` types it non-optional; 07 marks the
  nullable ones (``token_hash``, ``stats``, ``ordinal``, the timestamps
  that only a finished row has) and states ``NOT NULL`` where it wants it
  loudly (``tasks.terminal``, ``tasks.branch``).
- Timestamps are the store's to write, not the database's: the engine
  owns the clock (a retry keeps its task's ``created``, 03), so no
  timestamp column has a default.

The one table without foreign keys is ``events``. 07 §Schema marks a key
on every other child column — including the nullable ones,
``log_entries.task_id`` and ``join_arrivals.from_task`` — and marks none
on ``events.run_id``/``task_id``, which is what makes ``run.deleted``
possible: the outbox inserts its events when the transaction commits, so
an event naming the run that transaction deleted would violate a cascade
on the way in (18 §Run events). Removing a run's events is therefore
``RunRepo.delete``'s second statement, not the database's.
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    false,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

# Deterministic constraint names, so that the DDL Alembic generates from
# this metadata is the DDL it compares against on either backend.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)

#: JSON on SQLite (the ``JSON1`` functions), ``JSONB`` on PostgreSQL.
JSONV = JSON().with_variant(JSONB, "postgresql")

#: Every timestamp in the schema is timezone-aware; the store writes UTC.
TS = DateTime(timezone=True)


def _fk(target: str) -> ForeignKey:
    """A foreign key that takes its children with it.

    Every key in the schema cascades: it is what makes deleting a run one
    statement instead of nine, and what stops the MVP's orphaned messages
    from coming back (07 §Schema notes). SQLite only enforces any of it
    with ``PRAGMA foreign_keys=ON``, which
    :func:`athanore.store.engine.make_engine` sets on every connection.
    """

    return ForeignKey(target, ondelete="CASCADE")


runs = Table(
    "runs",
    metadata,
    Column("id", String, primary_key=True),
    Column("workflow", String, nullable=False),
    Column("status", String, nullable=False),
    Column("title", String, nullable=False),
    Column("description", Text, nullable=False, default=""),
    Column("output", JSONV),
    # List order, smaller first. Named `position` because a task's
    # `priority` is a different key (03 §Run).
    Column("position", Integer, nullable=False),
    Column("created", TS, nullable=False),
    Column("updated", TS, nullable=False),
    Column("finished", TS),
    Index("ix_runs_position", "position"),
    Index("ix_runs_status", "status"),
)

tasks = Table(
    "tasks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, _fk("runs.id"), nullable=False),
    Column("node", String, nullable=False),
    Column("attempt", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("payload", JSONV),
    Column("result", JSONV),
    Column("error", Text),
    Column("priority", Integer, nullable=False),
    Column("explicit", Boolean, nullable=False, default=False),
    # The SHA-256 of the task token, written at claim; the clear text is
    # returned once and never stored, and the column is NULL while the
    # task is `ready` (07 §Schema notes).
    Column("token_hash", String(64)),
    # The agent stats entry for this attempt (05), so a run's totals are
    # one aggregate rather than an event scan.
    Column("stats", JSONV),
    Column("lineage", JSONV),
    # Finished `done` with no transitions: the result is a branch output
    # (04 §Routing edge cases).
    Column("terminal", Boolean, nullable=False, default=False, server_default=false()),
    # The fan-out frame stack this task runs under, outermost first; `[]`
    # at top level (04 §Branch frames).
    Column(
        "branch",
        JSONV,
        nullable=False,
        default=list,
        server_default=text("'[]'"),
    ),
    Column("created", TS, nullable=False),
    Column("started", TS),
    Column("finished", TS),
    # The claim filters on status and then joins runs(position), so the
    # status leads (04 §Dispatch order).
    Index("ix_tasks_status_run_id", "status", "run_id"),
    Index("ix_tasks_run_id_id", "run_id", "id"),
    Index("ix_tasks_token_hash", "token_hash"),
)

log_entries = Table(
    "log_entries",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, _fk("runs.id"), nullable=False),
    Column("task_id", Integer, _fk("tasks.id")),
    Column("node", String, nullable=False),
    Column("author", String, nullable=False),
    Column("kind", String),
    Column("text", Text, nullable=False),
    Column("created", TS, nullable=False),
    Index("ix_log_entries_run_id_id", "run_id", "id"),
)

submissions = Table(
    "submissions",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", Integer, _fk("tasks.id"), nullable=False),
    Column("payload", JSONV),
    Column("created", TS, nullable=False),
    Index("ix_submissions_task_id_id", "task_id", "id"),
)

stream_chunks = Table(
    "stream_chunks",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("task_id", Integer, _fk("tasks.id"), nullable=False),
    # The cursor `GET /api/tasks/{id}/stream?after=` pages by; unique per
    # task, so a re-sent batch cannot duplicate the transcript.
    Column("seq", Integer, nullable=False),
    Column("kind", String, nullable=False),
    Column("text", Text, nullable=False),
    Column("created", TS, nullable=False),
    UniqueConstraint("task_id", "seq"),
)

requests = Table(
    "requests",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, _fk("runs.id"), nullable=False),
    Column("task_id", Integer, _fk("tasks.id"), nullable=False),
    # Numbers the node-raised requests of one task so a body that
    # re-executes after a restart re-attaches instead of asking again (06
    # §Restart durability); NULL for the agent-raised ones, of which a
    # task may have any number.
    Column("ordinal", Integer),
    Column("prompt", Text, nullable=False),
    Column("mode", String, nullable=False),
    Column("source", String, nullable=False),
    Column("kind", String, nullable=False),
    Column("options", JSONV),
    # `schema` is the wire name (08); the read model spells it `schema_`
    # because pydantic's BaseModel already has the attribute.
    Column("schema", JSONV),
    Column("tool_call", JSONV),
    Column("created", TS, nullable=False),
    Index("ix_requests_run_id", "run_id"),
    # Partial, so that many rows may hold NULL while a given
    # `(task_id, ordinal)` stays unique. Both dialect predicates are
    # required: with only one, the index silently becomes total on the
    # other backend and the second agent-raised request of a task is
    # rejected.
    Index(
        "uq_requests_task_ordinal",
        "task_id",
        "ordinal",
        unique=True,
        sqlite_where=text("ordinal IS NOT NULL"),
        postgresql_where=text("ordinal IS NOT NULL"),
    ),
)

answers = Table(
    "answers",
    metadata,
    # Keyed by the request: an answer without its request does not exist,
    # and a request has at most one (06 §The model).
    Column("request_id", Integer, _fk("requests.id"), primary_key=True),
    Column("author", String, nullable=False),
    Column("option_id", String),
    Column("value", JSONV),
    Column("consumed", Boolean, nullable=False, default=False),
    Column("created", TS, nullable=False),
)

join_arrivals = Table(
    "join_arrivals",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String, _fk("runs.id"), nullable=False),
    Column("join_node", String, nullable=False),
    # The task that fanned out, and this branch's place in that fan-out.
    # `fanout_task` is not a key: it identifies a frame, and the arrival
    # outlives nothing it points at (04 §Arrival and dispatch).
    Column("fanout_task", Integer, nullable=False),
    Column("index", Integer, nullable=False),
    Column("key", JSONV),
    Column("value", JSONV),
    Column("from_task", Integer, _fk("tasks.id")),
    # A branch that arrived again after the join had fired: recorded, not
    # dropped, and it does not re-fire the join.
    Column("late", Boolean, nullable=False, default=False),
    Column("created", TS, nullable=False),
    # The arrival is upserted before the join fires, so one index may
    # arrive twice but is stored once.
    UniqueConstraint("run_id", "join_node", "fanout_task", "index"),
)

events = Table(
    "events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("run_id", String),
    Column("task_id", Integer),
    Column("name", String, nullable=False),
    Column("data", JSONV, nullable=False, default=dict),
    Column("created", TS, nullable=False),
    Index("ix_events_run_id_id", "run_id", "id"),
    Index("ix_events_name_id", "name", "id"),
    # `events.id` is the SSE cursor. Without AUTOINCREMENT, SQLite reuses
    # the ids of deleted rows, so pruning the newest events would hand a
    # cursor back out and a subscriber past that point would never see
    # the rows that took the ids (D83).
    sqlite_autoincrement=True,
)

__all__ = [
    "JSONV",
    "NAMING_CONVENTION",
    "TS",
    "answers",
    "events",
    "join_arrivals",
    "log_entries",
    "metadata",
    "requests",
    "runs",
    "stream_chunks",
    "submissions",
    "tasks",
]
