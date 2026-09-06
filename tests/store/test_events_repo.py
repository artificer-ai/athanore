"""Tests for :mod:`athanore.store.repos.events`.

``events.id`` is the SSE cursor (08 §Events), so two things are asserted
harder than the rest. :meth:`EventRepo.insert_many` must hand back ids in
the order it was given events — it is the outbox's write path, and an id
that names the wrong event is a subscriber replaying from the wrong
place. And the glob must select whole segments: ``run.*`` is
``run.created`` and not ``run.a.b``. The bus enforces that rule in Python
(:func:`athanore.events.names.matches`); this module asserts the SQL
translation agrees with it, case by case, so a filtered replay and a
filtered live stream cannot disagree. ``matches`` is ``fnmatchcase``, so
the pairs include mis-cased ones: SQLite's ``LIKE`` folds ASCII case and
would select ``run.created`` for ``RUN.*``, which is why the wildcard half
is ``GLOB`` there (D89).

Every test runs on both backends; see ``tests/store/conftest.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from athanore.events.names import EventName, matches
from athanore.store.repos.events import glob_condition, like_pattern
from athanore.store.tables import events as events_table
from athanore.store.uow import Store

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


class Emitted:
    """The shape :meth:`EventRepo.insert_many` needs of an event.

    ``athanore.events.model.Event`` is one; ``store`` may not import it
    (02 §Layering), so the test states the same five fields.
    """

    def __init__(
        self,
        name: str,
        run_id: str | None = None,
        task_id: int | None = None,
        created: datetime | None = None,
        **data: Any,
    ) -> None:
        self.id: int | None = None
        self.run_id = run_id
        self.task_id = task_id
        self.name = name
        self.data: dict[str, Any] = dict(data)
        self.created = created or NOW


async def make_run(store: Store, title: str = "a run") -> str:
    async with store.uow() as uow:
        run = await uow.runs.insert("demo", title)
    return run.id


async def store_events(store: Store, *emitted: Emitted) -> list[int]:
    async with store.uow() as uow:
        return await uow.events.insert_many(list(emitted))


# --------------------------------------------------------------------------
# insert_many
# --------------------------------------------------------------------------


async def test_insert_many_returns_ascending_ids_in_order(store: Store) -> None:
    batch = [Emitted(f"plugin.demo.step{index}") for index in range(5)]

    ids = await store_events(store, *batch)

    assert ids == sorted(ids)
    assert len(set(ids)) == 5
    async with store.reader() as reader:
        stored = await reader.events.list_after(after=0, limit=10)
    assert [event.name for event in stored] == [event.name for event in batch]
    assert [event.id for event in stored] == ids


async def test_insert_many_writes_the_whole_envelope(store: Store) -> None:
    run_id = await make_run(store)

    await store_events(
        store,
        Emitted(EventName.task_done, run_id=run_id, task_id=7, node="build"),
    )

    async with store.reader() as reader:
        (stored,) = await reader.events.list_after(after=0, limit=10)
    assert (stored.run_id, stored.task_id, stored.name) == (
        run_id,
        7,
        EventName.task_done,
    )
    assert stored.data == {"node": "build"}
    assert stored.created.tzinfo is not None


async def test_insert_many_of_nothing_writes_nothing(store: Store) -> None:
    assert await store_events(store) == []

    async with store.reader() as reader:
        assert await reader.events.list_after(after=0, limit=10) == []


# --------------------------------------------------------------------------
# list_after
# --------------------------------------------------------------------------


async def test_list_after_honours_the_cursor_and_the_limit(store: Store) -> None:
    ids = await store_events(
        store, *(Emitted(EventName.log_appended) for _ in range(5))
    )

    async with store.reader() as reader:
        rest = await reader.events.list_after(after=ids[1], limit=10)
        page = await reader.events.list_after(after=ids[1], limit=2)

    assert [event.id for event in rest] == ids[2:]
    assert [event.id for event in page] == ids[2:4]


async def test_list_after_filters_by_run(store: Store) -> None:
    mine = await make_run(store, "mine")
    theirs = await make_run(store, "theirs")
    await store_events(
        store,
        Emitted(EventName.run_created, run_id=mine),
        Emitted(EventName.run_created, run_id=theirs),
        Emitted(EventName.engine_recovered),
    )

    async with store.reader() as reader:
        selected = await reader.events.list_after(after=0, limit=10, run_id=mine)

    assert [event.run_id for event in selected] == [mine]


@pytest.mark.parametrize(
    ("patterns", "expected"),
    [
        (["run.*"], ["run.created", "run.started"]),
        (["task.*"], ["task.done"]),
        (["run.*", "task.*"], ["run.created", "run.started", "task.done"]),
        (["plugin.*.*"], ["plugin.demo.built"]),
        (["*.created"], ["run.created"]),
        (["run.create?"], ["run.created"]),
        (["*"], []),
        (["nothing.*"], []),
    ],
)
async def test_list_after_selects_by_glob(
    store: Store, patterns: list[str], expected: list[str]
) -> None:
    """``*`` is one segment: ``run.*`` never reaches ``plugin.demo.built``."""

    names = [
        EventName.run_created.value,
        EventName.run_started.value,
        EventName.task_done.value,
        "plugin.demo.built",
    ]
    await store_events(store, *(Emitted(name) for name in names))

    async with store.reader() as reader:
        selected = await reader.events.list_after(after=0, limit=10, patterns=patterns)

    assert [event.name for event in selected] == expected


async def test_a_one_segment_glob_does_not_reach_a_deeper_name(
    store: Store,
) -> None:
    """The rule the query layer has to enforce as well as the bus does."""

    await store_events(store, Emitted("run.created"), Emitted("plugin.run.a"))

    async with store.reader() as reader:
        selected = await reader.events.list_after(after=0, limit=10, patterns=["run.*"])

    assert [event.name for event in selected] == ["run.created"]


async def test_no_patterns_is_no_filter(store: Store) -> None:
    """An empty sequence is "everything", not "nothing"."""

    await store_events(store, Emitted(EventName.run_created))

    async with store.reader() as reader:
        assert len(await reader.events.list_after(0, 10, patterns=[])) == 1
        assert len(await reader.events.list_after(0, 10, patterns=None)) == 1


@pytest.mark.parametrize(
    ("pattern", "name"),
    [
        ("run.*", "run.created"),
        ("run.*", "run.a.b"),
        ("run.*", "runs.created"),
        ("*", "run.created"),
        ("*", "engine"),
        ("*.*", "run.created"),
        ("plugin.*.*", "plugin.demo.built"),
        ("plugin.*.*", "plugin.demo"),
        ("plugin.*", "plugin.demo.built"),
        ("task.don?", "task.done"),
        ("task.don?", "task.donee"),
        ("task.done", "task.done"),
        ("task.done", "task.failed"),
        ("*.created", "run.created"),
        ("*.created", "a.b.created"),
        # Case is part of the rule: `matches` is `fnmatchcase` (D89).
        ("RUN.*", "run.created"),
        ("run.*", "RUN.CREATED"),
        ("task.DONE", "task.done"),
        ("TASK.don?", "task.done"),
        ("run.created", "run.created"),
    ],
)
async def test_the_sql_glob_agrees_with_the_bus(
    store: Store, pattern: str, name: str
) -> None:
    """One rule, two implementations, asserted equal case by case (D87)."""

    await store_events(store, Emitted(name))

    async with store.reader() as reader:
        selected = await reader.events.list_after(0, 10, patterns=[pattern])

    assert bool(selected) is matches(pattern, name)


async def test_a_character_class_is_refused_rather_than_mismatched(
    store: Store,
) -> None:
    async with store.reader() as reader:
        with pytest.raises(ValueError, match="character class"):
            await reader.events.list_after(0, 10, patterns=["run.[cd]*"])


async def test_a_miscased_pattern_selects_nothing(store: Store) -> None:
    """``RUN.*`` is not ``run.*``, on either backend (D89).

    SQLite's ``LIKE`` folds ASCII case, so the ``LIKE`` spelling of the
    glob selected this event there and not on PostgreSQL — and the bus,
    which is ``fnmatchcase``, selected it on neither. A filtered replay
    would have handed a subscriber an event its live stream never sends.
    """

    await store_events(store, Emitted("run.created"))

    async with store.reader() as reader:
        assert await reader.events.list_after(0, 10, patterns=["RUN.*"]) == []
        assert await reader.events.list_after(0, 10, patterns=["Run.Created"]) == []
        selected = await reader.events.list_after(0, 10, patterns=["run.*"])

    assert [event.name for event in selected] == ["run.created"]


def test_the_glob_is_spelled_per_backend() -> None:
    """``GLOB`` on SQLite, ``LIKE`` on PostgreSQL; the dot count on both."""

    condition = glob_condition(events_table.c.name, "run.*", "sqlite")
    sqlite_sql = str(condition.compile(dialect=sqlite.dialect()))
    assert "GLOB" in sqlite_sql
    assert "LIKE" not in sqlite_sql

    condition = glob_condition(events_table.c.name, "run.*", "postgresql")
    postgres_sql = str(condition.compile(dialect=postgresql.dialect()))
    assert "LIKE" in postgres_sql
    assert "GLOB" not in postgres_sql

    for sql in (sqlite_sql, postgres_sql):
        assert "replace(events.name" in sql


def test_the_glob_refuses_a_backend_it_has_no_spelling_for() -> None:
    with pytest.raises(NotImplementedError, match="event-name glob"):
        glob_condition(events_table.c.name, "run.*", "mysql")


async def test_a_pattern_may_not_smuggle_a_like_wildcard(store: Store) -> None:
    """``%`` is a literal in a glob; it must not become a wildcard."""

    await store_events(store, Emitted("run.created"), Emitted("run.%"))

    async with store.reader() as reader:
        selected = await reader.events.list_after(0, 10, patterns=["run.%"])

    assert [event.name for event in selected] == ["run.%"]


@pytest.mark.parametrize(
    ("glob", "like"),
    [
        ("run.*", "run.%"),
        ("task.don?", "task.don_"),
        ("run.%", "run.\\%"),
        ("a_b", "a\\_b"),
        ("a\\b", "a\\\\b"),
    ],
)
def test_like_pattern_escapes_what_it_does_not_translate(glob: str, like: str) -> None:
    assert like_pattern(glob) == like


# --------------------------------------------------------------------------
# list_for_run
# --------------------------------------------------------------------------


async def test_list_for_run_is_scoped_and_paged(store: Store) -> None:
    mine = await make_run(store, "mine")
    theirs = await make_run(store, "theirs")
    ids = await store_events(
        store,
        Emitted(EventName.run_created, run_id=mine),
        Emitted(EventName.run_started, run_id=mine),
        Emitted(EventName.run_created, run_id=theirs),
        Emitted(EventName.run_completed, run_id=mine),
    )

    async with store.reader() as reader:
        everything = await reader.events.list_for_run(mine)
        after_first = await reader.events.list_for_run(mine, after=ids[0])
        capped = await reader.events.list_for_run(mine, limit=1)

    assert [event.name for event in everything] == [
        EventName.run_created,
        EventName.run_started,
        EventName.run_completed,
    ]
    assert [event.name for event in after_first] == [
        EventName.run_started,
        EventName.run_completed,
    ]
    assert [event.name for event in capped] == [EventName.run_created]


# --------------------------------------------------------------------------
# prune
# --------------------------------------------------------------------------


async def test_prune_keeps_the_run_lifecycle_and_drops_the_rest(
    store: Store,
) -> None:
    old = NOW - timedelta(days=31)
    cutoff = NOW - timedelta(days=30)
    await store_events(
        store,
        Emitted(EventName.run_created, created=old),
        Emitted(EventName.run_completed, created=old),
        Emitted(EventName.task_done, created=old),
        Emitted(EventName.agent_stats, created=old),
        Emitted(EventName.task_done, created=NOW),
    )

    async with store.uow() as uow:
        removed = await uow.events.prune(cutoff)

    assert removed == 2
    async with store.reader() as reader:
        left = await reader.events.list_after(0, 10)
    assert [event.name for event in left] == [
        EventName.run_created,
        EventName.run_completed,
        EventName.task_done,
    ]


async def test_prune_with_no_prefix_keeps_nothing_old(store: Store) -> None:
    old = NOW - timedelta(days=31)
    await store_events(
        store,
        Emitted(EventName.run_created, created=old),
        Emitted(EventName.task_done, created=NOW),
    )

    async with store.uow() as uow:
        removed = await uow.events.prune(NOW - timedelta(days=30), keep_prefix="")

    assert removed == 1
    async with store.reader() as reader:
        assert [event.name for event in await reader.events.list_after(0, 10)] == [
            EventName.task_done
        ]


async def test_the_kept_prefix_is_case_sensitive(store: Store) -> None:
    """``run.`` keeps ``run.``, not ``RUN.`` (D89).

    The prefix was a ``LIKE`` until then, so SQLite kept a ``RUN.`` event
    that PostgreSQL deleted — the two backends disagreeing about what
    retention leaves behind.
    """

    old = NOW - timedelta(days=31)
    await store_events(
        store,
        Emitted("RUN.created", created=old),
        Emitted("run.created", created=old),
    )

    async with store.uow() as uow:
        removed = await uow.events.prune(NOW - timedelta(days=30))

    assert removed == 1
    async with store.reader() as reader:
        assert [event.name for event in await reader.events.list_after(0, 10)] == [
            "run.created"
        ]


async def test_a_kept_prefix_containing_a_like_wildcard_is_a_prefix(
    store: Store,
) -> None:
    """``%`` in the prefix is a literal, not "keep everything"."""

    old = NOW - timedelta(days=31)
    await store_events(
        store,
        Emitted("run.created", created=old),
        Emitted("%keep.me", created=old),
    )

    async with store.uow() as uow:
        removed = await uow.events.prune(NOW - timedelta(days=30), keep_prefix="%")

    assert removed == 1
    async with store.reader() as reader:
        assert [event.name for event in await reader.events.list_after(0, 10)] == [
            "%keep.me"
        ]


async def test_prune_does_not_touch_a_name_that_merely_starts_the_same(
    store: Store,
) -> None:
    """``run.`` is a prefix, not a substring, and the dot is a literal."""

    old = NOW - timedelta(days=31)
    await store_events(
        store,
        Emitted("runs.created", created=old),
        Emitted("run.created", created=old),
    )

    async with store.uow() as uow:
        removed = await uow.events.prune(NOW - timedelta(days=30))

    assert removed == 1
    async with store.reader() as reader:
        assert [event.name for event in await reader.events.list_after(0, 10)] == [
            "run.created"
        ]
