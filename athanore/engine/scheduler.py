"""The dispatch loop: what runs, when, and how many at once (04 §The loop).

Everything the loop uses already exists. Pools and leases are T022's,
the claim is the store's one concurrent query (07 §Repositories, 04
§Dispatch order), and an attempt is
:func:`~athanore.engine.runner.run_attempt`. What is here is the order
they happen in, which is the whole of the scheduling policy:

```
loop:
  reap finished attempts, release leases
  for pool in pools:
     drain the re-admit queue into the free slots
     claim what still fits, and spawn an attempt per claimed task
  await wake (notify() or a tick)
```

Three properties of that order are load-bearing.

- **Re-admits go before fresh claims.** A body that parked on a human
  and was answered is mid-execution and holding state, and it queued
  once already; a pool that let ``ready`` tasks in ahead of it would
  starve it for as long as work keeps arriving (04 §Waiting, D43).
- **Capacity is taken before the claim, not after it.** The loop
  acquires the free slots, claims at most that many tasks and releases
  the surplus, so a claimed row — already ``in_progress``, with its
  token minted — can never turn out to have no slot to run in. The
  reverse order has a case, however impossible, whose only outcome is a
  task stuck ``in_progress`` with nothing running it (D107).
- **The loop never dies.** An exception in a tick is logged and the next
  tick happens anyway: the alternative is a server that is up, accepts
  runs and quietly dispatches none of them. Logged, though — every
  time, with its traceback.

The loop does not decide anything else. It does not order tasks (the
claim does, and re-deriving that here would be the dispatch order
written twice), it does not recover interrupted rows (T027) and it does
not know what a workflow does. It also emits no events: ``task.started``
and the ``run.started`` of a run's first claim belong to the attempt
that goes on to run, and the runner publishes both (D102, D107).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Iterable, Sequence
from contextlib import asynccontextmanager, suppress
from typing import Final, NamedTuple, Protocol

from athanore.engine.pools import Lease, PoolRegistry, PoolState
from athanore.engine.runner import RunnerEngine, run_attempt
from athanore.logging import get_logger
from athanore.store.repos.tasks import ClaimedTask

_log = get_logger(__name__)

#: How long a tick waits to be woken before looking at the store anyway
#: (04 §The loop). Every path that can make a task ready calls
#: :meth:`Scheduler.notify`, so the tick is a safety net rather than the
#: mechanism; tests inject a shorter one.
DEFAULT_TICK: Final = 1.0


class _Attempt(NamedTuple):
    """What the scheduler holds for one spawned attempt.

    ``workflow`` is recorded at spawn from the claim, so
    :meth:`Scheduler.attempts_of` can answer for an attempt that has
    not yet bound its context — the live registry learns of one only
    after the runner's first await (D229).
    """

    task_id: int
    lease: Lease
    workflow: str


class SchedulerEngine(RunnerEngine, Protocol):
    """What the scheduler needs of the engine.

    The runner's six members plus the pool registry, for the same
    reason T024 named a protocol rather than importing the engine: the
    real :class:`athanore.engine.Engine` is T027's and satisfies this
    structurally, and a scheduler test that needed it would be testing
    the wiring instead of the loop.
    """

    @property
    def pools(self) -> PoolRegistry: ...


class Scheduler:
    """The dispatch loop of one engine, and the attempts it has spawned.

    Not thread-safe and not required to be: the loop, the attempts it
    spawns and every caller of :meth:`notify` are on the one event loop
    the engine runs.

    ``tick`` is how long :meth:`_wait` gives :meth:`notify` before it
    looks anyway. It is a constructor argument rather than a setting
    because nothing configures it in 02 §Configuration and only tests
    have a reason to move it (13 §Fakes: "the scheduler tick is injectable").
    """

    def __init__(self, engine: SchedulerEngine, *, tick: float = DEFAULT_TICK) -> None:
        self._engine = engine
        self.tick = tick
        self._wake = asyncio.Event()
        # Two views of the same attempts. `_attempts` answers "what is
        # running task 7", which is what an operator operation asks; the
        # reap walks `_live` instead, keyed by the asyncio task, because
        # one task id can have two attempts for a moment: `set_status(task,
        # ready)` re-dispatches a row whose cancelled attempt has not been
        # reaped yet (T027b), and the older one still holds a slot.
        self._attempts: dict[int, asyncio.Task[None]] = {}
        self._live: dict[asyncio.Task[None], _Attempt] = {}
        self._loop_task: asyncio.Task[None] | None = None
        # Held around every tick, so `quiescent()` can put a caller
        # between two of them. Free whenever the loop is not running.
        self._ticking = asyncio.Lock()

    # -- state -------------------------------------------------------------

    @property
    def running(self) -> bool:
        """Whether the dispatch loop is live in this process."""
        return self._loop_task is not None and not self._loop_task.done()

    @property
    def in_flight(self) -> tuple[int, ...]:
        """The ids of the tasks this process is running an attempt of.

        In spawn order, and a snapshot: an attempt that ends removes
        itself. This is what a shutdown lists in ``engine.stopping``
        (04 §Shutdown, T027).
        """
        return tuple(self._attempts)

    def attempts_of(self, workflow: str) -> list[int]:
        """The task ids of the live attempts of ``workflow``, in spawn order.

        Every attempt this process is running for the workflow — one
        inside its body, one parked in ``released()`` on a human (its
        row reads ``waiting``; the attempt is no less live), and one
        still loading before its first line. Each id once: a row
        re-dispatched under a live attempt has two attempts and one id.
        Exact only between ticks — a claim in progress may be about to
        add to it — which is what :meth:`quiescent` is for.
        """
        seen: dict[int, None] = {}
        for attempt, entry in self._live.items():
            if entry.workflow == workflow and not attempt.done():
                seen.setdefault(entry.task_id, None)
        return list(seen)

    def cancel_attempts_of(self, workflow: str) -> list[int]:
        """Cancel every live attempt of ``workflow``; the task ids, in spawn order.

        The cancel half of ``unregister`` (22 §Remove step 1). It reads
        the same ledger :meth:`attempts_of` and :meth:`wait_for` read —
        ``_live``, every attempt, not ``_attempts``, one per id — so the
        set it cancels is exactly the set that will be waited for. The
        difference is a row re-dispatched under a live attempt: the
        younger attempt never takes the id from the older one (D107),
        and once the older has ended it is the row's only attempt with
        no entry for :meth:`cancel_attempts` to find. It is still an
        attempt of the workflow, and it is cancelled here.

        Synchronous like :meth:`cancel_attempts`, and for the same
        reason: called between ticks, the set is closed, and the
        attempts reap themselves.
        """
        seen: dict[int, None] = {}
        for attempt, entry in self._live.items():
            if entry.workflow == workflow and not attempt.done():
                attempt.cancel()
                seen.setdefault(entry.task_id, None)
        return list(seen)

    async def wait_for(self, task_ids: Iterable[int]) -> None:
        """Wait for the attempts of ``task_ids`` to end, and reap them.

        The tail of a shutdown for a chosen set: every live attempt of
        those ids is awaited — the runner's ``finally`` and the façade's
        cleanup run to completion under it — and then reaped, so the
        slots are back and :attr:`in_flight` no longer lists them when
        this returns. Ids nothing is running are skipped. This does not
        cancel; the caller did, with :meth:`cancel_attempts` or
        :meth:`cancel_attempts_of`.
        """
        wanted = set(task_ids)
        attempts = [
            attempt for attempt, entry in self._live.items() if entry.task_id in wanted
        ]
        if attempts:
            await asyncio.gather(*attempts, return_exceptions=True)
        self._reap()

    @asynccontextmanager
    async def quiescent(self) -> AsyncGenerator[None]:
        """A block between ticks: no tick in progress, none starts.

        The tick in progress at entry finishes first, so every attempt a
        claim before now produced has been spawned (spawning is
        synchronous within the tick) and :meth:`attempts_of` is exact
        for the length of the block. The loop waits at its next tick
        until the block ends; ``notify()`` still works and is honoured
        by that tick. Free when the loop is not running, so it costs
        nothing before ``start()`` and after ``stop()``.

        Not reentrant, and meant to be short: a registry mutation, a
        cancellation, one store transaction. Never wait on an attempt
        inside it — an attempt's ``finally`` may be what the next tick
        is waiting to reap.
        """
        async with self._ticking:
            yield

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        """Start the dispatch loop.

        Returns once the loop task has begun its first tick, so a caller
        that starts the engine and immediately submits a run does not
        have to wonder whether anything is claiming yet. Starting a
        scheduler that is already running is a defect, not a no-op:
        two loops would claim against one set of pools.
        """
        if self.running:
            raise RuntimeError("the scheduler is already running")
        self._wake.clear()
        self._loop_task = asyncio.create_task(self._loop(), name="athanore-scheduler")
        await asyncio.sleep(0)

    async def stop_claiming(self) -> None:
        """End the dispatch loop, leaving the attempts it spawned running.

        Step 1 of 04 §Shutdown on its own, because the engine has one
        thing to do between it and step 3: ``engine.stopping`` names the
        attempts that were interrupted, and a loop still ticking could
        add to that set after it had been read (T027). Awaiting the loop
        task is what makes "no new attempts from here" true rather than
        merely likely.

        Idempotent, and safe on a scheduler that was never started.
        """
        loop_task, self._loop_task = self._loop_task, None
        if loop_task is not None:
            loop_task.cancel()
            with suppress(asyncio.CancelledError):
                await loop_task

    async def stop(self) -> None:
        """Stop claiming, then cancel every attempt and wait for it.

        Claiming stops first (04 §Shutdown step 1): cancelling attempts
        yields to the event loop, and a loop still ticking would spawn
        new attempts behind the ones being cancelled. No task status is
        written on the way out — an interrupted row stays ``in_progress``
        for recovery to reset, which is what makes a graceful stop and a
        crash leave the same store (D52).

        Idempotent, and safe on a scheduler that was never started.
        """
        await self.stop_claiming()
        await self._cancel_all()
        for pool in self._engine.pools:
            # The queue is in memory and its waiters have just been
            # cancelled; a restart recovers their tasks as `ready` rows
            # (04 §Shutdown, §Recovery on startup).
            pool.readmit.clear()

    def notify(self) -> None:
        """Wake the loop: something may have made a task ready.

        Called after every operation that can — submit, answer, retry,
        rerun, move, resume, and an attempt finishing (04 §The loop).
        Cheap and safe to call when the loop is not running: the flag is
        cleared at the top of the next tick.
        """
        self._wake.set()

    def cancel_attempts(self, task_ids: Iterable[int]) -> list[int]:
        """Cancel the attempts of ``task_ids``, and say which were live.

        The operator operations that end a task in flight — cancel,
        delete, move, ``set_status`` — record the outcome in their own
        transaction and then call this (T027b). Ids this process is not
        running an attempt of are skipped: an attempt is a fact about
        this process, not about the task.

        Synchronous by design. The attempt is cancelled here and reaps
        itself; the runner's ``finally`` gives the slot back, closes the
        transcript and wakes the loop.
        """
        cancelled: list[int] = []
        for task_id in task_ids:
            attempt = self._attempts.get(task_id)
            if attempt is None or attempt.done():
                continue
            attempt.cancel()
            cancelled.append(task_id)
        return cancelled

    # -- the loop ----------------------------------------------------------

    async def _loop(self) -> None:
        """Tick until cancelled, whatever a tick does.

        The guard is the outer one of two: :meth:`_dispatch_all` already
        contains a failure to one pool so the pools after it still get
        their turn, and this one keeps the loop alive through anything
        else — a reap that raised, a registry that did.
        """
        while True:
            # Cleared before the work, so a `notify()` raced against a
            # tick that had already looked is kept and wakes the next one.
            self._wake.clear()
            try:
                async with self._ticking:
                    await self._dispatch_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.error("scheduler tick failed", exc_info=True)
            await self._wait()

    async def _wait(self) -> None:
        """Wait for :meth:`notify`, or for ``tick`` seconds, whichever first."""
        with suppress(TimeoutError):
            async with asyncio.timeout(self.tick):
                await self._wake.wait()

    async def _dispatch_all(self) -> None:
        """One tick: reap what finished, then give every pool its turn."""
        self._reap()
        for pool in self._engine.pools:
            try:
                await self._dispatch_pool(pool)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.error("pool dispatch failed", pool=pool.name, exc_info=True)

    async def _dispatch_pool(self, pool: PoolState) -> None:
        """Re-admit, then claim, then spawn — for one pool.

        The re-admit queue is drained first and spends slots directly, so
        ``free()`` afterwards is what is left for new work. A pool with
        no capacity, no free slot or no workflow bound to it asks the
        store nothing.
        """
        pool.drain_readmits()
        free = pool.free()
        if free <= 0:
            return
        workflows = self._engine.pools.workflows_of(pool)
        if not workflows:
            return

        leases: list[Lease] = []
        while len(leases) < free:
            lease = pool.try_acquire()
            if lease is None:  # pragma: no cover - free() counted these
                break
            leases.append(lease)
        if not leases:  # pragma: no cover - free() > 0 guarantees one
            return

        try:
            claimed = await self._claim(len(leases), workflows)
        except BaseException:
            # The slots were reserved for a claim that never happened.
            for lease in leases:
                lease.release()
            raise

        # Fewer claimed than reserved is the ordinary case — the pool has
        # more room than the store has ready work — so the zip is not
        # strict and the leases left over go straight back.
        for one, lease in zip(claimed, leases, strict=False):
            self._spawn(one, lease)
        for surplus in leases[len(claimed) :]:
            surplus.release()

    async def _claim(self, limit: int, workflows: Sequence[str]) -> list[ClaimedTask]:
        """Take up to ``limit`` ready tasks of ``workflows``, in one uow.

        One transaction selects, claims, mints a token per task and
        starts the runs that were queued (04 §Dispatch order). The
        events for it are the attempt's, not the claim's: the runner
        publishes ``task.started``, and ``run.started`` for the task the
        claim flagged.
        """
        async with self._engine.store.uow() as uow:
            return await uow.tasks.claim_ready(limit, workflows)

    def _spawn(self, claimed: ClaimedTask, lease: Lease) -> None:
        """Run one attempt of ``claimed`` as its own asyncio task."""
        task_id = claimed.task.id
        lease.task_id = task_id
        attempt = asyncio.create_task(
            run_attempt(self._engine, claimed, lease),
            name=f"athanore-attempt-{task_id}",
        )
        self._live[attempt] = _Attempt(task_id, lease, claimed.workflow)
        previous = self._attempts.get(task_id)
        if previous is None or previous.done():
            # An attempt still running this task keeps the id. The row was
            # re-dispatched under it, this younger attempt refuses itself
            # in the live registry, and handing it the lookup would leave
            # the live one with nothing able to cancel it.
            self._attempts[task_id] = attempt
        attempt.add_done_callback(self._attempt_done)

    def _attempt_done(self, attempt: asyncio.Task[None]) -> None:
        """Wake the loop so the finished attempt is reaped promptly.

        The runner's ``finally`` already notifies on every path it runs,
        but an attempt cancelled before its first line ever ran has no
        ``finally`` to run — and it is still holding a slot until it is
        reaped. This callback is what gets that slot back.
        """
        del attempt
        self.notify()

    def _reap(self) -> None:
        """Drop the attempts that have ended and give their slots back.

        ``Lease.release`` is idempotent, so releasing here is a backstop
        for the runner's own ``finally`` rather than a second decrement —
        and the only release for an attempt that was cancelled before it
        began.

        An exception out of :func:`run_attempt` is a defect in the
        runner, which handles its own failures; there is nothing to
        record against the task from here, so it is logged with its
        traceback and the slot is recovered.
        """
        for attempt, (task_id, lease, _workflow) in list(self._live.items()):
            if not attempt.done():
                continue
            del self._live[attempt]
            # Only if this is still the attempt of that task: a
            # re-dispatched row has a newer one, and dropping it here
            # would hide it from `cancel_attempts`.
            if self._attempts.get(task_id) is attempt:
                del self._attempts[task_id]
            lease.release()
            if attempt.cancelled():
                continue
            error = attempt.exception()
            if error is not None:
                _log.error(
                    "attempt raised past the runner",
                    task_id=task_id,
                    exc_info=error,
                )

    async def _cancel_all(self) -> None:
        """Cancel every live attempt and wait for all of them to end."""
        attempts = list(self._live)
        for attempt in attempts:
            attempt.cancel()
        if attempts:
            await asyncio.gather(*attempts, return_exceptions=True)
        self._reap()

    def __repr__(self) -> str:
        state = "running" if self.running else "stopped"
        return f"Scheduler({state}, {len(self._live)} in flight)"
