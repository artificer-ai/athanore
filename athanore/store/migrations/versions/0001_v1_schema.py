"""v1 schema

The nine tables of 07 §Schema, as transcribed in
:mod:`athanore.store.tables`. This is the only place in the tree that
creates them: nothing constructs a table on the side, and nothing runs
``metadata.create_all`` outside a test.

The file is deliberately self-contained — a migration is frozen history,
so it repeats the JSON variant and the naming convention's names rather
than importing them from a module that will keep changing. Its
correctness is not left to review: ``tests/store/test_migrations.py``
upgrades an empty database and asserts that Alembic finds no difference
between it and ``tables.metadata``.

Revision ID: 0001
Revises:
Created: 2026-09-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: JSON on SQLite, ``JSONB`` on PostgreSQL, as `athanore.store.tables`
#: declares it. A fresh instance per column: SQLAlchemy types are bound
#: to the column they are attached to.
def _jsonv() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


#: Every timestamp in the schema is timezone-aware; the store writes UTC.
def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("workflow", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("output", _jsonv(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created", _ts(), nullable=False),
        sa.Column("updated", _ts(), nullable=False),
        sa.Column("finished", _ts(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_runs"),
    )
    op.create_index("ix_runs_position", "runs", ["position"], unique=False)
    op.create_index("ix_runs_status", "runs", ["status"], unique=False)

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("node", sa.String(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("payload", _jsonv(), nullable=True),
        sa.Column("result", _jsonv(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("explicit", sa.Boolean(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=True),
        sa.Column("stats", _jsonv(), nullable=True),
        sa.Column("lineage", _jsonv(), nullable=True),
        # `false()`, not `text("0")`: PostgreSQL refuses an integer
        # default on a boolean column.
        sa.Column("terminal", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("branch", _jsonv(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column("created", _ts(), nullable=False),
        sa.Column("started", _ts(), nullable=True),
        sa.Column("finished", _ts(), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_tasks_run_id_runs", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
    )
    op.create_index(
        "ix_tasks_status_run_id", "tasks", ["status", "run_id"], unique=False
    )
    op.create_index("ix_tasks_run_id_id", "tasks", ["run_id", "id"], unique=False)
    op.create_index("ix_tasks_token_hash", "tasks", ["token_hash"], unique=False)

    op.create_table(
        "log_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("node", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_log_entries_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_log_entries_task_id_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_log_entries"),
    )
    op.create_index(
        "ix_log_entries_run_id_id", "log_entries", ["run_id", "id"], unique=False
    )

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("payload", _jsonv(), nullable=True),
        sa.Column("created", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_submissions_task_id_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_submissions"),
    )
    op.create_index(
        "ix_submissions_task_id_id", "submissions", ["task_id", "id"], unique=False
    )

    op.create_table(
        "stream_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_stream_chunks_task_id_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stream_chunks"),
        sa.UniqueConstraint("task_id", "seq", name="uq_stream_chunks_task_id_seq"),
    )

    op.create_table(
        "requests",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=True),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("options", _jsonv(), nullable=True),
        sa.Column("schema", _jsonv(), nullable=True),
        sa.Column("tool_call", _jsonv(), nullable=True),
        sa.Column("created", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["runs.id"], name="fk_requests_run_id_runs", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_requests_task_id_tasks",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_requests"),
    )
    op.create_index("ix_requests_run_id", "requests", ["run_id"], unique=False)
    # Partial on both backends: with only one predicate the index becomes
    # total on the other, and a task's second agent-raised request (both
    # `ordinal IS NULL`) would be rejected.
    op.create_index(
        "uq_requests_task_ordinal",
        "requests",
        ["task_id", "ordinal"],
        unique=True,
        sqlite_where=sa.text("ordinal IS NOT NULL"),
        postgresql_where=sa.text("ordinal IS NOT NULL"),
    )

    op.create_table(
        "answers",
        sa.Column("request_id", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("option_id", sa.String(), nullable=True),
        sa.Column("value", _jsonv(), nullable=True),
        sa.Column("consumed", sa.Boolean(), nullable=False),
        sa.Column("created", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["requests.id"],
            name="fk_answers_request_id_requests",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("request_id", name="pk_answers"),
    )

    op.create_table(
        "join_arrivals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=False),
        sa.Column("join_node", sa.String(), nullable=False),
        sa.Column("fanout_task", sa.Integer(), nullable=False),
        sa.Column("index", sa.Integer(), nullable=False),
        sa.Column("key", _jsonv(), nullable=True),
        sa.Column("value", _jsonv(), nullable=True),
        sa.Column("from_task", sa.Integer(), nullable=True),
        sa.Column("late", sa.Boolean(), nullable=False),
        sa.Column("created", _ts(), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_task"],
            ["tasks.id"],
            name="fk_join_arrivals_from_task_tasks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["runs.id"],
            name="fk_join_arrivals_run_id_runs",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_join_arrivals"),
        sa.UniqueConstraint(
            "run_id",
            "join_node",
            "fanout_task",
            "index",
            name="uq_join_arrivals_run_id_join_node_fanout_task_index",
        ),
    )

    # No foreign keys, so that the `run.deleted` event the deleting
    # transaction emits can still be inserted (D83); AUTOINCREMENT
    # because `events.id` is the SSE cursor and SQLite would otherwise
    # hand a pruned row's id back out.
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("data", _jsonv(), nullable=False),
        sa.Column("created", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_events"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_events_run_id_id", "events", ["run_id", "id"], unique=False)
    op.create_index("ix_events_name_id", "events", ["name", "id"], unique=False)


def downgrade() -> None:
    # Children first: the cascades are on delete, not on drop. Each
    # table takes its own indexes with it on both backends.
    op.drop_table("events")
    op.drop_table("join_arrivals")
    op.drop_table("answers")
    op.drop_table("requests")
    op.drop_table("stream_chunks")
    op.drop_table("submissions")
    op.drop_table("log_entries")
    op.drop_table("tasks")
    op.drop_table("runs")
