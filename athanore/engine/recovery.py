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
"""

from __future__ import annotations

from typing import Protocol

from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.events.payloads import EngineRecovered
from athanore.graph import Graph
from athanore.logging import get_logger
from athanore.store.clock import now
from athanore.store.uow import Store

_log = get_logger(__name__)


class RecoverableEngine(Protocol):
    """What :func:`recover` needs of the engine: the store and the registry.

    A protocol for the reason the runner's and the scheduler's are: the
    real :class:`athanore.engine.Engine` satisfies it structurally, and
    recovery is testable against anything that carries those two members.
    """

    @property
    def store(self) -> Store: ...

    @property
    def graphs(self) -> dict[str, Graph]: ...


async def recover(engine: RecoverableEngine) -> list[int]:
    """Reset this engine's interrupted attempts and announce them.

    One transaction: the ``UPDATE`` and its ``engine.recovered``. The
    event carries the ids and no ``run_id`` — it is about the process
    starting, not about any one run (18 §Engine) — and it is emitted only
    when there was something to recover, because an event announcing that
    nothing happened is noise in every timeline that has to be read.

    Returns the ids that were reset, in ascending order, which is what a
    host logs and what a test asserts on.
    """

    workflows = sorted(engine.graphs)
    async with engine.store.uow() as uow:
        task_ids = await uow.tasks.reset_for_recovery(workflows)
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
