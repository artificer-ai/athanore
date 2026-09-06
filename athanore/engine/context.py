"""The object a node body sees, and the contextvar it is bound in.

04 §TaskContext. A node body is an ordinary async function: it takes edge
references and a payload and returns a value. Everything else it needs —
which run it belongs to, which attempt this is, the token an agent will
authenticate with, the narrow services that reach the store — arrives
through this object, and it arrives out of band because putting it in the
signature would break rule 1 (the signature *is* the graph: a parameter is
an edge, not an injection point).

Out of band means a :class:`contextvars.ContextVar`, set by the runner for
the duration of the attempt:

.. code-block:: python

    with bind(ctx):
        value = await node.fn(*edge_refs)

:func:`current_task` is what every user-land helper calls —
``human_input``, an agent façade, a plugin action running against a task.
It raises outside a body rather than returning ``None``, because a helper
that quietly did nothing when it was called from the wrong place is a bug
that shows up much later and somewhere else. :func:`maybe_current_task` is
for the callers that legitimately have no task: prompt assembly outside a
run (T034), a plugin route resolved from query parameters (09).

A ``ContextVar`` is per-:class:`asyncio.Task`, so a fan-out that spawns
tasks inside a body does **not** inherit the binding automatically unless
those tasks are created inside the ``with`` block — which they are, since
``asyncio.create_task`` copies the current context at creation. Nested
binds restore the outer context on exit, which is what lets one body
enter another's context (a join collecting branch results) without losing
its own.

The two private fields are the engine's, not user land's:
:attr:`TaskContext._timeout` is the ``asyncio.Timeout`` the runner wrapped
the body in, and :attr:`TaskContext._released_at` is the loop clock when a
waiting body gave its slot back. T026 reads both to reschedule the node
timeout across a human wait, so that a human taking a day does not fail an
attempt capped at ten minutes of agent time (04 §Waiting).
"""

from __future__ import annotations

import asyncio
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel

from athanore.engine.services import TaskServices


@dataclass
class TaskContext:
    """Everything one attempt of one node knows about itself (04).

    The first block is the attempt's identity and never changes while it
    is bound. The second is declared by an agent façade for the duration
    of ``run()`` and restored afterwards (``Agent.declare``, T034), which
    is what lets one body run two agents with different output models.
    The third is engine-owned bookkeeping.

    ``token`` is the task token in clear text. It lives here and in the
    prompt handed to the agent, and nowhere else: it is never in an
    operator response and never in an event (12 §Task tokens).
    """

    run_id: str
    task_id: int
    workflow: str
    node: str
    attempt: int
    #: The task token, clear text (12). Header-only; never serialised.
    token: str
    #: What an agent is told to call: ``settings.public_url``.
    api_base: str
    services: TaskServices

    # Declared by an agent façade for the duration of `run()` (05).
    output_model: type[BaseModel] | None = None
    ask_policy: Literal["off", "http"] = "off"
    last_rejection: dict[str, Any] | None = None

    # Engine-owned counters and handles.
    #: The nth ``human_input()`` of this attempt (06 §Restart durability).
    request_ordinal: int = 0
    #: The runner's ``asyncio.timeout`` scope, rescheduled across a wait.
    _timeout: asyncio.Timeout | None = field(default=None, repr=False)
    #: ``loop.time()`` when this attempt released its slot, if it is waiting.
    _released_at: float | None = field(default=None, repr=False)


#: The binding. ``None`` means "no attempt is running on this task".
_current: ContextVar[TaskContext | None] = ContextVar(
    "athanore_task_context", default=None
)


@contextmanager
def bind(ctx: TaskContext) -> Generator[TaskContext, None, None]:
    """Bind ``ctx`` as the current task for the duration of the block.

    Restores whatever was bound before — including nothing — on the way
    out, on every path. Nesting is supported and is not a mistake: a body
    that runs another body's context restores its own afterwards, and a
    fan-out that lost its context on the way back would be unfixable from
    outside.
    """
    token = _current.set(ctx)
    try:
        yield ctx
    finally:
        _current.reset(token)


def current_task() -> TaskContext:
    """The bound :class:`TaskContext`, or raise.

    Raises ``RuntimeError("no task context")`` when nothing is bound. It
    raises rather than returning ``None`` because every caller needs the
    context to do its job: ``human_input`` with nowhere to record the
    request, an agent façade with no token to hand out. Silently doing
    less is how a workflow appears to run and produces nothing.
    """
    ctx = _current.get()
    if ctx is None:
        raise RuntimeError("no task context")
    return ctx


def maybe_current_task() -> TaskContext | None:
    """The bound :class:`TaskContext`, or ``None`` outside an attempt.

    For the callers that have a defensible answer with no task: prompt
    assembly outside a run, a plugin route scoped to a workflow rather
    than a task.
    """
    return _current.get()


__all__ = ["TaskContext", "bind", "current_task", "maybe_current_task"]
