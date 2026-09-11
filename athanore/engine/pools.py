"""Named capacity pools, slot leases and the re-admit queue (04 §Pools).

A pool is a concurrency cap with a name. Nothing else: what an agent
talks to, and how long it takes, is invisible here. The rules carried
from the MVP hold unchanged — strict reservation (no lending between
pools), ``capacity=0`` parks a workflow, names are unique and cannot
collide with a workflow name, and a task's pool is derived from
``run.workflow`` and never changes.

New in v1 is the **lease**. The runner holds a :class:`Lease` for the
duration of an attempt and releases it in a ``finally``; a body that
parks on a human gives its lease back while it waits (04 §Waiting) and
has to get one again to carry on. Getting one again is the **re-admit
queue**: a per-pool FIFO of tasks whose answer has arrived, drained by
the scheduler loop *before* it asks the store for new work, so a
half-finished body beats every ``ready`` task in the pool. Leases and
the queue are in memory, which is the whole of their crash semantics: a
restart frees every lease and empties every queue, and recovery turns
the tasks back into ``ready`` rows (04 §Recovery).

This module owns capacity accounting and nothing else. It never claims a
task, never touches the store and never runs a body: the loop that calls
it is the scheduler's (T025), and the release/re-acquire pair around a
wait is the lease service's (T026).
"""

from __future__ import annotations

import asyncio
import re
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypedDict

#: A pool name is lower snake case: it is written by hand in Python and
#: in ``athanore.toml``, and it shares a namespace with workflow names.
POOL_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class Pool:
    """A named concurrency cap, as a user writes it.

    ``Pool("sandbox", capacity=1)`` is public API: it is passed to
    ``Server.register(wf, pool=…)`` and read out of ``athanore.toml``, so
    it is frozen and validates itself on construction rather than
    failing later inside the scheduler. "Dedicated" and "shared" are not
    two features — a dedicated pool is one that exactly one workflow
    happens to be registered on.

    ``capacity=0`` is legal and means "queue only, never dispatch": the
    workflow's tasks accumulate as ``ready`` rows and nothing claims
    them until the pool is given capacity.
    """

    name: str
    capacity: int

    def __post_init__(self) -> None:
        if not POOL_NAME.match(self.name):
            raise ValueError(
                f"pool name {self.name!r} is not a valid name: it must match "
                f"{POOL_NAME.pattern}"
            )
        # Public API takes what a user wrote, so the type is checked at
        # runtime too. Exactly `int`, not a subclass of it: `bool` is an
        # `int`, and `Pool("sandbox", True)` is a typo rather than a cap
        # of one.
        if type(self.capacity) is not int:
            raise ValueError(
                f"pool {self.name!r} capacity must be an int, got {self.capacity!r}"
            )
        if self.capacity < 0:
            raise ValueError(
                f"pool {self.name!r} capacity must be >= 0, got {self.capacity}"
            )


class PoolSnapshot(TypedDict):
    """One pool as ``/api/health`` and ``/api/workflows`` report it."""

    capacity: int
    in_flight: int


class Lease:
    """One slot of a pool, held for one stretch of work.

    A lease is handed out by :meth:`PoolState.try_acquire` or by the
    re-admit queue, and returned by :meth:`release`. Releasing twice is a
    no-op: the runner's ``finally`` releases the lease it holds whether
    or not the body already gave it back inside ``released()``, and a
    second decrement would manufacture capacity out of nothing.
    """

    __slots__ = ("pool_state", "task_id", "_released")

    def __init__(self, pool_state: PoolState, task_id: int | None = None) -> None:
        self.pool_state = pool_state
        self.task_id = task_id
        self._released = False

    @property
    def released(self) -> bool:
        """Whether this lease has already been given back."""
        return self._released

    def release(self) -> None:
        """Return the slot to the pool. Idempotent."""
        if self._released:
            return
        if self.pool_state.leased <= 0:  # pragma: no cover - unreachable
            raise RuntimeError(
                f"pool {self.pool_state.name!r} released a slot it never leased"
            )
        self._released = True
        self.pool_state.leased -= 1

    def __repr__(self) -> str:
        state = "released" if self._released else "held"
        return (
            f"Lease(pool={self.pool_state.name!r}, task_id={self.task_id!r}, {state})"
        )


#: A queued re-admit: who is waiting, the future the lease is delivered
#: on, and when it joined the queue. The tuple is what the deque holds,
#: and ``enqueued_at`` is the loop clock, so it is comparable with the
#: node timeout arithmetic that surrounds a wait (T026).
Waiter = tuple[int, "asyncio.Future[Lease]", float]


class PoolState:
    """The live half of a :class:`Pool`: what is leased, and who waits.

    One of these per pool, owned by the :class:`PoolRegistry`. It is not
    thread-safe and does not need to be: every caller is on the one
    event loop the engine runs.
    """

    def __init__(self, pool: Pool) -> None:
        self.pool = pool
        self.leased = 0
        self.readmit: deque[Waiter] = deque()

    @property
    def name(self) -> str:
        return self.pool.name

    @property
    def capacity(self) -> int:
        return self.pool.capacity

    def free(self) -> int:
        """Slots available right now, never negative."""
        return max(self.capacity - self.leased, 0)

    def try_acquire(self, task_id: int | None = None) -> Lease | None:
        """Take a slot if there is one, else ``None``.

        This is the *only* way new capacity is spent outside the
        re-admit queue, and it never waits: the scheduler asks for as
        many as :meth:`free` says it can have and claims that many tasks.
        """
        if self.free() <= 0:
            return None
        self.leased += 1
        return Lease(self, task_id)

    def release(self, lease: Lease) -> None:
        """Give ``lease`` back to this pool. Idempotent.

        Raises ``ValueError`` for a lease of another pool: a slot
        returned to the wrong pool is capacity lent between pools, which
        is exactly what strict reservation forbids.
        """
        if lease.pool_state is not self:
            raise ValueError(
                f"lease of pool {lease.pool_state.name!r} released on pool "
                f"{self.name!r}"
            )
        lease.release()

    def request_readmit(self, task_id: int) -> asyncio.Future[Lease]:
        """Join the re-admit queue; await the result for the new lease.

        Deliberately not a coroutine. The waiter's place in the queue is
        taken when this is *called*, not when the returned future is
        first awaited, so a body that has been answered cannot lose its
        position to one answered after it. The scheduler hands the lease
        over in :meth:`drain_readmits`; cancelling the await removes the
        waiter, without ever spending a slot on it.

        The future is the return type rather than a bare ``Awaitable``
        because a caller cancelled in the window between
        :meth:`drain_readmits` setting the result and the waiter resuming
        holds the only reference to a lease the pool has already spent,
        and has to be able to see it and give it back (T026).
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Lease] = loop.create_future()
        self.readmit.append((task_id, future, loop.time()))
        return future

    def drain_readmits(self) -> list[Lease]:
        """Hand a lease to each waiter, oldest first, while slots remain.

        Returns the leases handed over, which is what tells the
        scheduler how much of ``free()`` the queue has already spent. A
        waiter whose future is already done — the body was cancelled, or
        the wait timed out — is dropped without consuming a slot.
        """
        handed: list[Lease] = []
        while self.readmit and self.free() > 0:
            task_id, future, _enqueued_at = self.readmit.popleft()
            if future.done():
                continue
            lease = self.try_acquire(task_id)
            if lease is None:  # pragma: no cover - free() > 0 guarantees one
                break
            future.set_result(lease)
            handed.append(lease)
        return handed

    def snapshot(self) -> PoolSnapshot:
        """This pool's counts, as the wire reports them."""
        return PoolSnapshot(capacity=self.capacity, in_flight=self.leased)

    def __repr__(self) -> str:
        return (
            f"PoolState({self.name!r}, capacity={self.capacity}, "
            f"leased={self.leased}, readmit={len(self.readmit)})"
        )


class PoolRegistry:
    """Every pool the engine knows, and which workflow runs on which.

    Pool names and workflow names share one namespace (04 §Pools), so
    the registry refuses a pool named after a registered workflow and a
    workflow named after a pool, whichever arrives second: with the two
    confused, ``athanore.toml``'s ``[pools]`` and ``[workflows]`` tables
    could not name their subject.

    A workflow is bound to exactly one pool. :meth:`bind` to the same
    pool is a no-op (registering a workflow twice is the host's error to
    report, not a capacity change); :meth:`bind` to a different one
    raises, because a task's pool is derived from ``run.workflow`` and
    a move under the attempts already leased against the old pool would
    charge one pool's work to another's capacity. A live registration
    (22 §Pools) moves a binding through :meth:`rebind` and drops one
    through :meth:`unbind`; neither looks at what is in flight, because
    the registry does not know — the engine does, and it refuses the
    move before it calls here (04 §Pools).
    """

    def __init__(self) -> None:
        self._pools: dict[str, PoolState] = {}
        self._bindings: dict[str, str] = {}

    def add(self, pool: Pool) -> PoolState:
        """Register ``pool``. Raises ``ValueError`` on a name clash."""
        if pool.name in self._pools:
            raise ValueError(f"pool {pool.name!r} is already registered")
        if pool.name in self._bindings:
            raise ValueError(
                f"pool name {pool.name!r} is already the name of a workflow"
            )
        state = PoolState(pool)
        self._pools[pool.name] = state
        return state

    def bind(self, workflow: str, pool_name: str) -> PoolState:
        """Run ``workflow`` on ``pool_name``, and return that pool's state."""
        if workflow in self._pools:
            raise ValueError(
                f"workflow name {workflow!r} is already the name of a pool"
            )
        if pool_name not in self._pools:
            raise ValueError(
                f"workflow {workflow!r} names pool {pool_name!r}, which is not "
                f"registered; known pools are {sorted(self._pools)}"
            )
        bound = self._bindings.get(workflow)
        if bound is not None and bound != pool_name:
            raise ValueError(
                f"workflow {workflow!r} is already bound to pool {bound!r} and "
                f"cannot be moved to {pool_name!r}"
            )
        self._bindings[workflow] = pool_name
        return self._pools[pool_name]

    def unbind(self, workflow: str) -> None:
        """Drop ``workflow``'s binding; the pool stays (22 §Remove step 2).

        Raises ``KeyError`` for a name that is not bound, as
        :meth:`for_workflow` does: this is a lookup that found nothing,
        not a registration that is wrong. Afterwards :meth:`workflows_of`
        no longer lists the name, so no claim selects its tasks (04
        §Dispatch order), and :meth:`for_workflow` raises for it.
        """
        try:
            del self._bindings[workflow]
        except KeyError:
            raise KeyError(f"workflow {workflow!r} is not bound to a pool") from None

    def rebind(self, workflow: str, pool_name: str) -> PoolState:
        """Move ``workflow`` to ``pool_name``; return that pool's state.

        The one way a binding changes pools (22 §Replace step 1). Both
        failures are ``KeyError`` — an unbound workflow, an unknown pool —
        because both are lookups, and the caller that maps errors to the
        wire has to tell "no such pool" from the engine's own refusal of
        a move with attempts in flight, which is a ``ValueError``. The
        same pool is a no-op.
        """
        if workflow not in self._bindings:
            raise KeyError(f"workflow {workflow!r} is not bound to a pool")
        if pool_name not in self._pools:
            raise KeyError(
                f"no pool named {pool_name!r}; known pools are {sorted(self._pools)}"
            )
        self._bindings[workflow] = pool_name
        return self._pools[pool_name]

    def get(self, pool_name: str) -> PoolState:
        """The state of ``pool_name``. Raises ``KeyError`` if unknown."""
        try:
            return self._pools[pool_name]
        except KeyError:
            raise KeyError(f"no pool named {pool_name!r}") from None

    def for_workflow(self, workflow: str) -> PoolState:
        """The pool ``workflow`` runs on. Raises ``KeyError`` if unbound.

        Unbound is a defect rather than a state to tolerate: a run
        exists for a workflow the host never registered, so there is no
        capacity to charge its tasks to and no honest default to invent.
        """
        try:
            pool_name = self._bindings[workflow]
        except KeyError:
            raise KeyError(f"workflow {workflow!r} is not bound to a pool") from None
        return self._pools[pool_name]

    def workflows_of(self, pool: str | Pool | PoolState) -> tuple[str, ...]:
        """The workflows bound to ``pool``, in binding order.

        This is the ``r.workflow IN (…)`` of the dispatch query (04
        §Dispatch order): the pool asks the store only for work that is
        its to run.
        """
        name = _pool_name(pool)
        if name not in self._pools:
            raise KeyError(f"no pool named {name!r}")
        return tuple(
            workflow for workflow, bound in self._bindings.items() if bound == name
        )

    def snapshot(self) -> dict[str, PoolSnapshot]:
        """Every pool's counts, keyed by name, in registration order."""
        return {name: state.snapshot() for name, state in self._pools.items()}

    def __iter__(self) -> Iterator[PoolState]:
        """Iterate the pools in registration order — the scheduler's loop."""
        return iter(list(self._pools.values()))

    def __len__(self) -> int:
        return len(self._pools)

    def __contains__(self, pool_name: object) -> bool:
        return pool_name in self._pools

    def __repr__(self) -> str:
        return f"PoolRegistry({sorted(self._pools)!r})"


def _pool_name(pool: str | Pool | PoolState) -> str:
    return pool if isinstance(pool, str) else pool.name
