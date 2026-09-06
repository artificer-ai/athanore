"""The registry of in-flight task contexts (02 §Package layout).

The store says what a task *is*; this says what is running it right
now. A task's context exists only between the moment the runner binds it
and the moment the attempt ends, and it is the only route from a task id
to the live objects of that attempt — the lease, the agent, the stream
buffer. Operator operations reach a running attempt through it
(``cancel``), and so does anything that has a task id and needs the
attempt behind it rather than the row.

It is in memory by definition: a restart empties it, and recovery turns
what it held back into ``ready`` rows (04 §Recovery). Nothing here is
durable and nothing here is authoritative — a task absent from the
registry is a task no attempt of this process is running, which is a
fact about the process, not about the task.

:class:`TaskContext` arrives in T023, so the registry names what it needs
structurally: a context is anything carrying a ``task_id``.
"""

from __future__ import annotations

from typing import Protocol


class LiveContext(Protocol):
    """What :class:`LiveRegistry` needs of a context: its task id.

    ``athanore.engine.context.TaskContext`` (T023) satisfies this
    structurally. Naming the shape rather than importing the class keeps
    the registry independent of everything the context will grow —
    services, the lease, the agent — and keeps this module importable on
    its own.
    """

    @property
    def task_id(self) -> int: ...


class LiveRegistry:
    """The contexts of the attempts running in this process.

    Not thread-safe and not required to be: the runner registers and
    unregisters on the engine's event loop, and every reader is on it
    too.
    """

    def __init__(self) -> None:
        self._contexts: dict[int, LiveContext] = {}

    def register(self, ctx: LiveContext) -> None:
        """Record ``ctx`` as the live context of its task.

        Raises ``ValueError`` if that task already has one. Two live
        contexts for one task id would mean two attempts of the same
        task running at once, which the claim predicate makes impossible
        (07 §Repositories) — so it is a defect in the runner, and the
        second context silently winning would hide it.
        """
        task_id = ctx.task_id
        if task_id in self._contexts:
            raise ValueError(f"task {task_id!r} already has a live context")
        self._contexts[task_id] = ctx

    def unregister(self, task_id: int) -> LiveContext | None:
        """Drop ``task_id``'s context and return it, if it had one.

        Idempotent: the runner unregisters in a ``finally``, which also
        runs on the paths where registration never happened.
        """
        return self._contexts.pop(task_id, None)

    def context_for(self, task_id: int) -> LiveContext | None:
        """``task_id``'s live context, or ``None`` if it is not running here."""
        return self._contexts.get(task_id)

    def all(self) -> list[LiveContext]:
        """Every live context, in registration order.

        A copy: callers iterate it while cancelling attempts, and a
        cancelled attempt unregisters itself.
        """
        return list(self._contexts.values())

    def __contains__(self, task_id: object) -> bool:
        return task_id in self._contexts

    def __len__(self) -> int:
        return len(self._contexts)

    def __repr__(self) -> str:
        return f"LiveRegistry({len(self._contexts)} live)"
