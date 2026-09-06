"""The event vocabulary: every name the system can emit, and how to match one.

03 §Event vocabulary fixes the names, 18 fixes the payload each carries
(:mod:`athanore.events.payloads`). This module is the one place a name is
spelled: everything else references ``EventName.task_done`` rather than a
string literal, so a rename is a type error instead of a silent miss.

Plugins own the ``plugin.`` namespace. Their names are not enum members —
they are declared by workflows at runtime — but they are still part of the
vocabulary, which is what :func:`is_known` exists to say.
"""

from __future__ import annotations

from enum import StrEnum
from fnmatch import fnmatchcase

#: Namespace reserved for plugin-published events (18 §Plugins).
PLUGIN_PREFIX = "plugin."

#: Segment count of a well-formed plugin name: ``plugin.<workflow>.<name>``.
_PLUGIN_SEGMENTS = 3


class EventName(StrEnum):
    """Every event name in the vocabulary, one member per row of 03.

    Values are ``subject.verb``. Adding one is a change to 03 and to the
    TypeScript mirror, never to this module alone.
    """

    # Runs
    run_created = "run.created"
    run_started = "run.started"
    run_updated = "run.updated"
    run_reordered = "run.reordered"
    run_paused = "run.paused"
    run_resumed = "run.resumed"
    run_cancelled = "run.cancelled"
    run_deleted = "run.deleted"
    run_completed = "run.completed"
    run_failed = "run.failed"

    # Tasks
    task_enqueued = "task.enqueued"
    join_arrived = "join.arrived"
    task_started = "task.started"
    task_done = "task.done"
    task_failed = "task.failed"
    task_dead_lettered = "task.dead_lettered"
    task_waiting = "task.waiting"
    task_resumed = "task.resumed"
    task_cancelled = "task.cancelled"
    task_moved = "task.moved"
    task_status_set = "task.status_set"
    task_stream = "task.stream"

    # Submissions and requests
    submission_accepted = "submission.accepted"
    submission_rejected = "submission.rejected"
    submission_repair = "submission.repair"
    request_opened = "request.opened"
    request_answered = "request.answered"

    # Log and stats
    log_appended = "log.appended"
    agent_stats = "agent.stats"

    # Engine
    engine_recovered = "engine.recovered"
    engine_stopping = "engine.stopping"


#: Events that are published and streamed but never stored (03). At two to
#: three flushes per second per streaming task, `task.stream` would be most
#: of the events table, and it carries no state a late joiner cannot rebuild
#: from `StreamChunk`.
EPHEMERAL: frozenset[EventName] = frozenset({EventName.task_stream})

_VALUES: frozenset[str] = frozenset(member.value for member in EventName)


def is_known(name: str) -> bool:
    """Is ``name`` part of the vocabulary?

    True for an :class:`EventName` member, and for a plugin name of the form
    ``plugin.<workflow>.<name>`` whose two further segments are identifiers.
    The registry enforces that ``<workflow>`` is the publishing workflow
    (18 §Plugins); this function only knows the shape.
    """
    if name in _VALUES:
        return True
    if not name.startswith(PLUGIN_PREFIX):
        return False
    segments = name.split(".")
    return len(segments) == _PLUGIN_SEGMENTS and all(
        segment.isidentifier() for segment in segments[1:]
    )


def matches(pattern: str, name: str) -> bool:
    """Does the glob ``pattern`` select the event ``name``?

    ``fnmatch`` per dotted segment, so a ``*`` matches exactly one segment:
    ``run.*`` selects ``run.created`` but not ``run.a.b``, and a subscriber
    after plugin events asks for ``plugin.*.*``. Patterns are the SSE
    ``names`` filter (08 §Events) and a plugin panel's ``refresh_on`` (09).
    """
    pattern_segments = pattern.split(".")
    name_segments = name.split(".")
    if len(pattern_segments) != len(name_segments):
        return False
    return all(
        fnmatchcase(segment, pattern_segment)
        for pattern_segment, segment in zip(
            pattern_segments, name_segments, strict=True
        )
    )
