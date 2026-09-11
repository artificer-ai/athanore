"""Execution: scheduler, pools, runner, routing, recovery, operator ops.

:class:`Engine` is the object that owns them. It is one process's view of
a store: which workflows this server can run, what capacity they run on,
what is running right now, and the two lifecycle paths that decide
whether a restart loses work.

.. code-block:: python

    engine = Engine(settings, store, bus)
    engine.register(feature_build.finalize(), Pool("local", 1))
    await engine.start()      # recovery, then the dispatch loop
    ...
    await engine.replace(feature_build.finalize())   # the next claim runs this
    await engine.unregister("feature_build")         # cancel, unbind, drop
    ...
    await engine.stop()       # stop claiming, announce, cancel, wait

Everything above the engine reaches it through this object —
``engine.ops`` for the operator operations, ``engine.graphs`` for what is
registered, ``engine.pools`` for the capacity report — and everything
below it is reached *by* it. It holds no state of its own beyond those
registries: the store is the truth, and a restart rebuilds this object
from an empty one.

The registries are live (04 §Live registration, 22 §Effects).
:meth:`Engine.register` is the boot-time verb and refuses a name it
has; :meth:`Engine.replace` swaps the graph under a name while the
engine runs, and :meth:`Engine.unregister` cancels the name's attempts
and drops it. Every mutation that has to be exact about what is in
flight runs between two scheduler ticks
(:meth:`~athanore.engine.scheduler.Scheduler.quiescent`), because a
claim is an await inside a tick and anything checked across one can be
stale by exactly the attempt that claim is about to spawn.

Two orderings here are load-bearing and neither is arbitrary.

- **Recovery runs before the scheduler starts.** The loop claims
  ``ready`` rows, and recovery rewrites the rows a dead process left
  behind; started the other way round, the loop could claim a row in the
  window before recovery reset it, and the attempt it spawned would be
  racing the ``UPDATE`` that was about to clear its token.
- **Shutdown stops claiming, then announces, then cancels** (04
  §Shutdown). Announcing first would name a set of attempts the loop
  could still be adding to; cancelling first would lose the record of
  what was interrupted, since a cancelled attempt writes no status by
  design (D52).

The engine satisfies the three protocols the modules under it declare —
``RunnerEngine``, ``SchedulerEngine`` and ``OpsEngine`` — structurally
rather than by inheritance, so none of them has to import this module
and each states exactly how much of the engine it touches.
"""

from __future__ import annotations

import asyncio
from typing import Final

from athanore.engine.errors import (
    Conflict,
    EngineError,
    NonRetryable,
    NotFound,
    UnknownNode,
    UnknownWorkflow,
    is_retryable,
)
from athanore.engine.live import LiveRegistry
from athanore.engine.ops import Ops
from athanore.engine.pools import Pool, PoolRegistry, PoolSnapshot
from athanore.engine.recovery import recover
from athanore.engine.scheduler import DEFAULT_TICK, Scheduler
from athanore.engine.services import RequestBackend
from athanore.events.bus import EventBus
from athanore.events.model import Event
from athanore.events.names import EventName
from athanore.events.payloads import EngineStopping
from athanore.graph import Graph
from athanore.logging import get_logger
from athanore.settings import AthanoreSettings
from athanore.store.clock import now
from athanore.store.uow import Store

_log = get_logger(__name__)

#: What a graceful stop is given, in total, before the host stops waiting
#: for it (04 §Shutdown: "total budget 10 s"). Past it the process exits
#: anyway — uvicorn's ``timeout_graceful_shutdown`` is the outer one — so
#: overrunning is logged and returned from rather than raised.
SHUTDOWN_BUDGET: Final = 10.0

#: The pool a workflow registered without one runs on, sized by
#: ``settings.workers`` (04 §Pools). Created on first use, so a server
#: whose workflows all name their own pool never has one.
DEFAULT_POOL: Final = "default"


class Engine:
    """One process's execution of the workflows registered on it."""

    def __init__(
        self,
        settings: AthanoreSettings,
        store: Store,
        bus: EventBus,
        *,
        requests: RequestBackend | None = None,
        tick: float = DEFAULT_TICK,
    ) -> None:
        self.settings = settings
        self.store = store
        #: The bus the store publishes committed events to. The concrete
        #: :class:`~athanore.events.bus.EventBus` rather than the store's
        #: ``EventPublisher`` protocol: what everything above the engine
        #: wants of it is ``subscribe`` (the SSE feed, T046), and the
        #: store's half of it is the half this attribute is not for.
        self.bus = bus
        #: The one :class:`~athanore.requests.service.RequestService` of
        #: this process, or ``None``. It arrives from the composition root
        #: rather than being built here because ``athanore.requests`` is
        #: this package's sibling and neither may import the other (02
        #: §Layering) — the engine states the shape it needs
        #: (:class:`~athanore.engine.services.RequestBackend`) and the
        #: host that builds both hands it over. Without it every attempt
        #: gets a request port whose methods raise, which is what an
        #: engine that cannot ask anybody anything should do.
        self.requests = requests
        self.pools = PoolRegistry()
        self.graphs: dict[str, Graph] = {}
        self.live = LiveRegistry()
        self.scheduler = Scheduler(self, tick=tick)
        self.ops = Ops(self)

    # -- registration ------------------------------------------------------

    def register(self, graph: Graph, pool: Pool | None = None) -> None:
        """Run ``graph``'s workflow on ``pool``.

        ``pool`` defaults to :data:`DEFAULT_POOL`, sized by
        ``settings.workers`` — 04 §Pools' "the default pool is sized by
        ``workers``" — and a second workflow registered without a pool
        joins the same one rather than getting a second cap.

        Registering the same graph twice is refused: the pool registry
        already rejects a re-bind to a different pool, and a silent
        rebind of the graph itself would leave running attempts
        executing the object this call replaced — :meth:`replace` is the
        verb for a swap. Name clashes between a pool and a workflow are
        the registry's to refuse (04 §Pools).
        """

        name = graph.name
        registered = self.graphs.get(name)
        if registered is not None and registered is not graph:
            raise ValueError(f"workflow {name!r} is already registered")
        if pool is None:
            pool = Pool(DEFAULT_POOL, self.settings.workers)
        if pool.name not in self.pools:
            self.pools.add(pool)
        self.pools.bind(name, pool.name)
        self.graphs[name] = graph

    async def replace(self, graph: Graph, pool: str | Pool | None = None) -> None:
        """Swap the graph registered under ``graph.name`` (22 §Replace step 1).

        The next claim of the workflow dispatches on ``graph``; an
        attempt in flight finishes on the graph it started with, routing
        included, because the runner read the registry at its claim and
        holds the object (04 §Live registration). A task whose node the
        new graph does not declare dead-letters at its attempt with
        ``GraphError`` (D42), exactly as it would after a restart.

        ``pool`` is ``None`` to keep the binding, else the *name* of a
        registered pool to move the workflow to; a :class:`Pool` object
        contributes only its name, since creating or resizing a pool is
        not a registration's to do (22 §Scope, D233). The move is refused
        with ``ValueError`` while any attempt of the workflow is in
        flight (22 §Pools): its leases belong to the pool they were
        claimed on. ``KeyError`` for a name that is not registered and
        for a pool that does not exist — both lookups, checked before
        the in-flight refusal so a typo is reported as a typo. A refusal
        leaves the engine exactly as it was.

        A coroutine because the in-flight check is exact only between
        ticks (:meth:`~athanore.engine.scheduler.Scheduler.quiescent`).
        """

        name = graph.name
        if name not in self.graphs:
            raise KeyError(f"workflow {name!r} is not registered")
        if pool is None:
            self.graphs[name] = graph
            return
        pool_name = pool if isinstance(pool, str) else pool.name
        async with self.scheduler.quiescent():
            if pool_name != self.pools.for_workflow(name).name:
                if pool_name not in self.pools:
                    raise KeyError(
                        f"no pool named {pool_name!r}; known pools are "
                        f"{sorted(state.name for state in self.pools)}"
                    )
                live = self.scheduler.attempts_of(name)
                if live:
                    raise ValueError(
                        f"workflow {name!r} cannot move from pool "
                        f"{self.pools.for_workflow(name).name!r} to {pool_name!r} "
                        f"with attempts in flight: tasks {live}"
                    )
                self.pools.rebind(name, pool_name)
            self.graphs[name] = graph

    async def unregister(self, name: str) -> list[int]:
        """Drop the workflow ``name``, cancelling what it is running.

        22 §Remove steps 1–2, in this order and between ticks: the name
        is unbound from its pool, so no claim from here selects its
        tasks (04 §Dispatch order); every attempt this process holds —
        running, parked on a human, still loading, or the second attempt
        of a row re-dispatched under a live one — is cancelled the way
        :meth:`stop` cancels them; the graph is dropped; then, with
        the loop free to tick again, the cancelled attempts are waited
        for so their slots are back and their contexts gone when this
        returns. Returns the task ids that were interrupted, in spawn
        order — what ``workflow.unregistered`` announces.

        What each cancellation does is the attempt's own cancellation
        path: the agent subprocess terminated then killed under the grace
        period, the transcript flushed, the façade's stats entry written
        as for any cancellation (``status=failed reason=shutdown``),
        ``released()`` re-raising with no resume. **No task status is
        written** and the run row is not touched (D52, D221): the rows
        stay ``in_progress`` / ``waiting`` for the next ``add`` of the
        name, or the next process, to recover. The pool stays: it is the
        host's capacity, and other workflows may be on it.

        ``KeyError`` for a name that is not registered. Safe on an engine
        that was never started — nothing is in flight, and the registries
        are simply edited.
        """

        if name not in self.graphs:
            raise KeyError(f"workflow {name!r} is not registered")
        async with self.scheduler.quiescent():
            self.pools.unbind(name)
            # Every live attempt of the name — the set `wait_for` waits
            # on — not `cancel_attempts`' one-per-id ledger, which has
            # no entry for the younger attempt of a re-dispatched row
            # once the older one has ended (D107).
            task_ids = self.scheduler.cancel_attempts_of(name)
            # Dropped synchronously with the cancellations: an attempt
            # still loading its run is cancelled at that await and never
            # looks the graph up; one before its first line never runs.
            del self.graphs[name]
        await self.scheduler.wait_for(task_ids)
        if task_ids:
            _log.info(
                "unregistered with attempts in flight", workflow=name, task_ids=task_ids
            )
        return task_ids

    def attempts_of(self, workflow: str) -> list[int]:
        """The task ids of the attempts of ``workflow`` this process is running.

        In spawn order, each once; a snapshot, exact between ticks. What
        the server's ``remove`` reports and what ``replace`` refuses a
        pool move over (22 §Effects).
        """

        return self.scheduler.attempts_of(workflow)

    def snapshot(self) -> dict[str, PoolSnapshot]:
        """Every pool's capacity and in-flight count (08 §System)."""

        return self.pools.snapshot()

    # -- the runner's and the ops' one call back into the engine -----------

    def notify(self) -> None:
        """Wake the dispatch loop: something may have made a task ready.

        The engine's method rather than the scheduler's because that is
        what the runner and the operator operations hold (D102): they
        know the engine, and which object inside it owns the loop is not
        theirs to know.
        """

        self.scheduler.notify()

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Recover the last process's attempts, then start claiming.

        In that order, and never the reverse: see the module docstring.
        Returns once the loop has begun its first tick, so a caller that
        starts the engine and immediately submits a run does not have to
        wonder whether anything is claiming yet.
        """

        await recover(self)
        await self.scheduler.start()

    async def stop(self) -> None:
        """Stop the engine the way 04 §Shutdown says to.

        Claiming stops, the interrupted attempts are announced in one
        transaction (``engine.stopping {task_ids}``), and only then is
        every attempt cancelled and waited for. **No task status is
        written**: an interrupted row stays ``in_progress`` or
        ``waiting`` for recovery to reset, which is what makes a graceful
        stop and a crash leave the same store (D52) — and what makes the
        next :meth:`start` pick the work back up.

        The whole of it is under :data:`SHUTDOWN_BUDGET`. Overrunning is
        logged rather than raised: the host is on its way out either way,
        and an exception here would only replace a slow shutdown with a
        noisy one.

        Idempotent, and safe on an engine that was never started.
        """

        await self.scheduler.stop_claiming()
        try:
            async with asyncio.timeout(SHUTDOWN_BUDGET):
                await self._announce_stopping()
                await self.scheduler.stop()
        except TimeoutError:
            _log.error(
                "shutdown exceeded its budget",
                budget_s=SHUTDOWN_BUDGET,
                in_flight=self.scheduler.in_flight,
            )

    async def _announce_stopping(self) -> None:
        """Record the attempts this shutdown is about to interrupt.

        One transaction, before the cancellations, so the audit trail
        shows the interruption even though no row will carry it: the
        tasks keep the status they had, and this event is the only thing
        that says why they stopped. Nothing is emitted when nothing is in
        flight — a quiet shutdown interrupted nobody.
        """

        task_ids = list(self.scheduler.in_flight)
        if not task_ids:
            return
        async with self.store.uow() as uow:
            uow.emit(
                Event(
                    run_id=None,
                    task_id=None,
                    name=EventName.engine_stopping,
                    data=EngineStopping(task_ids=task_ids).model_dump(),
                    created=now(),
                )
            )
        _log.info("stopping with attempts in flight", task_ids=task_ids)

    def __repr__(self) -> str:
        return (
            f"Engine({len(self.graphs)} workflows, {len(self.pools)} pools, "
            f"{len(self.live)} live)"
        )


__all__ = [
    "DEFAULT_POOL",
    "SHUTDOWN_BUDGET",
    "Conflict",
    "Engine",
    "EngineError",
    "NonRetryable",
    "NotFound",
    "Ops",
    "Pool",
    "UnknownNode",
    "UnknownWorkflow",
    "is_retryable",
    "recover",
]
