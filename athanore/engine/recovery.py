"""What startup does about the attempts the last process was running.

04 §Recovery on startup, and it is two rules rather than one:

1. every ``in_progress`` or ``waiting`` task of a **registered** workflow
   goes back to ``ready`` with its token hash cleared, and
   ``engine.recovered`` lists them;
2. a run whose workflow is not registered here is left exactly as it is.

The first is the durability posture of 04 §Durability made concrete: an
attempt that was interrupted re-executes from scratch, so the row it left
behind has to become claimable again, and the token it authenticated with
has to stop working (D38). A graceful stop leaves the same rows a crash
does — the shutdown deliberately writes no task status (D52) — so there
is one path here, not two.

The second is the rule that is easy to get wrong. Resetting the tasks of
a workflow nobody has registered would make them ``ready`` rows that no
pool can ever claim (the claim filters by workflow, 04 §Dispatch order),
so the run would read as work that is about to happen and never would.
Left alone, an interrupted attempt of an unregistered workflow keeps the
status it had, and the API flags the run ``unregistered`` from
``engine.graphs`` — which is the honest report: this server does not
have the code that run needs.

Recovery re-runs nothing itself. It makes rows claimable and returns; the
scheduler is what dispatches them, and :meth:`athanore.engine.Engine.start`
runs this first for exactly that reason.

The same sweep runs for one name after start, when a workflow is added
to a serving engine (22 §Add step 3, 04 §Live registration): the rows
an earlier ``unregister`` left ``in_progress``/``waiting`` — or a dead
process did — become claimable the moment the code is back. Two things
make that safe on a loop that is ticking. The sweep runs between ticks
(:meth:`~athanore.engine.scheduler.Scheduler.quiescent`), and it skips
the rows held by attempts of this process: the name is bound before
recovery is asked for, so a tick in between may already have claimed a
``ready`` row of it, and a reset under that attempt would put a second
one on the same task (D229).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from athanore.engine.scheduler import Scheduler
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.events.payloads import EngineRecovered
from athanore.graph import Graph
from athanore.logging import get_logger
from athanore.store.clock import now
from athanore.store.uow import Store

_log = get_logger(__name__)


class RecoverableEngine(Protocol):
    """What :func:`recover` needs of the engine: store, registry, scheduler.

    A protocol for the reason the runner's and the scheduler's are: the
    real :class:`athanore.engine.Engine` satisfies it structurally, and
    recovery is testable against anything that carries those members.
    The scheduler is here for the runtime case — what is in flight, and
    the gap between ticks to read it in; at boot it is idle and costs
    nothing.
    """

    @property
    def store(self) -> Store: ...

    @property
    def graphs(self) -> dict[str, Graph]: ...

    @property
    def scheduler(self) -> Scheduler: ...


async def recover(
    engine: RecoverableEngine, workflows: Sequence[str] | None = None
) -> list[int]:
    """Reset this engine's interrupted attempts and announce them.

    One transaction: the ``UPDATE`` and its ``engine.recovered``. The
    event carries the ids and no ``run_id`` — it is about the process
    starting, not about any one run (18 §Engine) — and it is emitted only
    when there was something to recover, because an event announcing that
    nothing happened is noise in every timeline that has to be read.

    ``workflows`` is ``None`` for every registered workflow — what
    ``start()`` asks for — or the names to sweep, each of which must be
    registered: ``KeyError`` names the ones that are not, because
    resetting the rows of a workflow nothing can claim is the defect the
    module docstring describes. Rows held by a live attempt of this
    engine are left alone, and the sweep runs between ticks, so a name
    added to a running engine recovers exactly the rows nothing is
    running (22 §Add step 3).

    Returns the ids that were reset, in ascending order, which is what a
    host logs and what a test asserts on.
    """

    if workflows is None:
        names = sorted(engine.graphs)
    else:
        names = list(dict.fromkeys(workflows))
        unknown = [name for name in names if name not in engine.graphs]
        if unknown:
            raise KeyError(
                f"cannot recover unregistered workflows {unknown}; registered "
                f"workflows are {sorted(engine.graphs)}"
            )
    async with engine.scheduler.quiescent():
        held = [
            task_id for name in names for task_id in engine.scheduler.attempts_of(name)
        ]
        async with engine.store.uow() as uow:
            task_ids = await uow.tasks.reset_for_recovery(names, exclude=held)
            if task_ids:
                uow.emit(
                    Event(
                        run_id=None,
                        task_id=None,
                        name=EventName.engine_recovered,
                        data=EngineRecovered(task_ids=task_ids).model_dump(),
                        created=now(),
                    )
                )
    if task_ids:
        _log.info("recovered interrupted attempts", task_ids=task_ids)
    return task_ids


__all__ = ["RecoverableEngine", "recover"]
