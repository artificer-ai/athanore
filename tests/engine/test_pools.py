"""Capacity accounting: pools, leases and the re-admit queue (T022).

The subtle behaviour is the queue's: a body that parked on a human and
was answered has to get a slot back *ahead of* every ready task in its
pool, or a busy pool starves everything already half-done (04 §Waiting,
D43). So the ordering assertions are the point of this file — the rest
is arithmetic that must not drift.
"""

import asyncio
from dataclasses import FrozenInstanceError

import pytest

from athanore.engine.pools import (
    Lease,
    Pool,
    PoolRegistry,
    PoolState,
)


def state(capacity: int, name: str = "sandbox") -> PoolState:
    return PoolState(Pool(name, capacity=capacity))


# --- Pool: public API, so it validates itself ------------------------------


def test_pool_is_frozen():
    pool = Pool("sandbox", capacity=2)
    with pytest.raises(FrozenInstanceError):
        pool.capacity = 3  # type: ignore[misc]


@pytest.mark.parametrize(
    "name", ["sandbox", "local", "a", "pool_2", "default", "a_b_c9"]
)
def test_pool_accepts_lower_snake_case(name: str):
    assert Pool(name, capacity=1).name == name


@pytest.mark.parametrize(
    "name", ["", "Sandbox", "2pool", "_private", "with-dash", "with space", "wf.pool"]
)
def test_pool_rejects_a_name_outside_the_pattern(name: str):
    with pytest.raises(ValueError, match="not a valid name"):
        Pool(name, capacity=1)


def test_pool_rejects_a_negative_capacity():
    with pytest.raises(ValueError, match=">= 0"):
        Pool("sandbox", capacity=-1)


@pytest.mark.parametrize("capacity", ["1", 1.0, True, None])
def test_pool_rejects_a_capacity_that_is_not_an_int(capacity: object):
    with pytest.raises(ValueError, match="must be an int"):
        Pool("sandbox", capacity=capacity)  # type: ignore[arg-type]


# --- try_acquire / release ------------------------------------------------


def test_capacity_zero_never_acquires():
    parked = state(0)
    assert parked.free() == 0
    assert parked.try_acquire(1) is None
    assert parked.try_acquire(2) is None
    assert parked.leased == 0


def test_acquiring_spends_capacity_and_stops_at_the_cap():
    pool = state(2)
    first = pool.try_acquire(1)
    second = pool.try_acquire(2)
    assert isinstance(first, Lease)
    assert isinstance(second, Lease)
    assert pool.free() == 0
    assert pool.try_acquire(3) is None
    assert pool.leased == 2


def test_release_then_acquire():
    pool = state(1)
    lease = pool.try_acquire(1)
    assert lease is not None
    assert pool.try_acquire(2) is None

    lease.release()

    assert lease.released is True
    assert pool.free() == 1
    again = pool.try_acquire(2)
    assert again is not None
    assert again.task_id == 2


def test_double_release_does_not_manufacture_capacity():
    pool = state(1)
    lease = pool.try_acquire(1)
    assert lease is not None

    lease.release()
    lease.release()
    pool.release(lease)

    assert pool.leased == 0
    assert pool.free() == 1  # never 2, whatever the cap
    assert pool.try_acquire(2) is not None
    assert pool.try_acquire(3) is None


def test_release_through_the_pool_is_the_same_release():
    pool = state(1)
    lease = pool.try_acquire(1)
    assert lease is not None

    pool.release(lease)

    assert lease.released is True
    assert pool.free() == 1


def test_a_lease_cannot_be_released_on_another_pool():
    mine = state(1, "sandbox")
    theirs = state(1, "local")
    lease = mine.try_acquire(1)
    assert lease is not None

    with pytest.raises(ValueError, match="released on pool 'local'"):
        theirs.release(lease)

    assert mine.leased == 1  # no lending between pools, in either direction
    assert theirs.leased == 0


def test_a_lease_repr_names_its_pool_task_and_state():
    pool = state(1)
    lease = pool.try_acquire(1)
    assert lease is not None
    assert "sandbox" in repr(lease)
    assert "task_id=1" in repr(lease)
    assert "held" in repr(lease)
    lease.release()
    assert "released" in repr(lease)


# --- the re-admit queue ---------------------------------------------------


async def test_a_readmit_waits_until_a_slot_is_drained():
    pool = state(1)
    held = pool.try_acquire(1)
    assert held is not None

    waiting = pool.request_readmit(2)
    assert pool.drain_readmits() == []  # nothing free, nothing handed

    held.release()
    handed = pool.drain_readmits()

    assert len(handed) == 1
    lease = await waiting
    assert lease is handed[0]
    assert lease.task_id == 2
    assert pool.leased == 1
    assert pool.free() == 0


async def test_a_parked_pool_never_serves_its_readmit_queue():
    parked = state(0, "parked")
    waiting = asyncio.ensure_future(parked.request_readmit(1))

    assert parked.drain_readmits() == []
    assert len(parked.readmit) == 1
    assert not waiting.done()

    waiting.cancel()


async def test_drain_readmits_serves_a_readmit_before_a_fresh_acquire():
    """The whole point of the queue: half-done work goes first."""
    pool = state(1)
    waiting = pool.request_readmit(1)

    handed = pool.drain_readmits()  # the scheduler drains before it claims
    fresh = pool.try_acquire(2)  # ...and only then asks for new work

    assert [lease.task_id for lease in handed] == [1]
    assert fresh is None
    assert (await waiting).task_id == 1


async def test_readmits_are_served_fifo():
    pool = state(2)
    held = [pool.try_acquire(100 + n) for n in range(2)]
    waiters = [pool.request_readmit(n) for n in range(4)]

    assert pool.drain_readmits() == []  # full: the queue waits its turn
    for lease in held:
        assert lease is not None
        lease.release()

    first = pool.drain_readmits()
    assert [lease.task_id for lease in first] == [0, 1]
    assert pool.free() == 0

    for lease in first:
        lease.release()
    second = pool.drain_readmits()
    assert [lease.task_id for lease in second] == [2, 3]

    assert [(await waiter).task_id for waiter in waiters] == [0, 1, 2, 3]


async def test_a_waiters_place_is_taken_when_it_asks_not_when_it_awaits():
    pool = state(1)
    first = pool.request_readmit(1)
    second = asyncio.ensure_future(pool.request_readmit(2))

    handed = pool.drain_readmits()

    assert [lease.task_id for lease in handed] == [1]
    assert (await first).task_id == 1
    assert not second.done()

    second.cancel()


async def test_a_cancelled_waiter_is_dropped_without_spending_a_slot():
    pool = state(1)
    gone = asyncio.ensure_future(pool.request_readmit(1))
    still_there = pool.request_readmit(2)

    gone.cancel()
    with pytest.raises(asyncio.CancelledError):
        await gone

    handed = pool.drain_readmits()

    assert [lease.task_id for lease in handed] == [2]
    assert (await still_there).task_id == 2
    assert pool.leased == 1


async def test_drain_readmits_stops_at_the_cap_and_keeps_the_rest_queued():
    pool = state(2)
    waiters = [pool.request_readmit(n) for n in range(3)]

    handed = pool.drain_readmits()

    assert len(handed) == 2
    assert len(pool.readmit) == 1

    handed[0].release()
    assert [lease.task_id for lease in pool.drain_readmits()] == [2]
    await asyncio.gather(*waiters)


async def test_a_readmitted_lease_is_released_like_any_other():
    pool = state(1)
    waiting = pool.request_readmit(1)
    pool.drain_readmits()

    lease = await waiting
    lease.release()

    assert pool.leased == 0
    assert pool.try_acquire(2) is not None


def test_pool_state_snapshot_and_repr():
    pool = state(2)
    assert pool.snapshot() == {"capacity": 2, "in_flight": 0}
    pool.try_acquire(1)
    assert pool.snapshot() == {"capacity": 2, "in_flight": 1}
    assert "sandbox" in repr(pool)


# --- the registry ---------------------------------------------------------


def test_add_returns_the_state_and_snapshot_counts_it():
    pools = PoolRegistry()
    sandbox = pools.add(Pool("sandbox", capacity=2))
    pools.add(Pool("local", capacity=0))

    sandbox.try_acquire(1)

    assert pools.snapshot() == {
        "sandbox": {"capacity": 2, "in_flight": 1},
        "local": {"capacity": 0, "in_flight": 0},
    }
    assert list(pools.snapshot()) == ["sandbox", "local"]  # registration order
    assert len(pools) == 2
    assert "sandbox" in pools and "nope" not in pools
    assert [state.name for state in pools] == ["sandbox", "local"]


def test_add_rejects_a_duplicate_pool_name():
    pools = PoolRegistry()
    pools.add(Pool("sandbox", capacity=1))
    with pytest.raises(ValueError, match="already registered"):
        pools.add(Pool("sandbox", capacity=4))


def test_add_rejects_a_pool_named_after_a_workflow():
    pools = PoolRegistry()
    pools.add(Pool("local", capacity=1))
    pools.bind("sandbox", "local")

    with pytest.raises(ValueError, match="already the name of a workflow"):
        pools.add(Pool("sandbox", capacity=1))


def test_bind_rejects_a_workflow_named_after_a_pool():
    pools = PoolRegistry()
    pools.add(Pool("sandbox", capacity=1))

    with pytest.raises(ValueError, match="already the name of a pool"):
        pools.bind("sandbox", "sandbox")


def test_bind_rejects_an_unregistered_pool():
    pools = PoolRegistry()
    pools.add(Pool("local", capacity=1))

    with pytest.raises(ValueError, match="which is not registered"):
        pools.bind("build", "sandbox")


def test_bind_is_idempotent_but_will_not_move_a_workflow():
    pools = PoolRegistry()
    pools.add(Pool("local", capacity=1))
    pools.add(Pool("sandbox", capacity=1))

    assert pools.bind("build", "local") is pools.bind("build", "local")

    with pytest.raises(ValueError, match="already bound to pool 'local'"):
        pools.bind("build", "sandbox")
    assert pools.workflows_of("sandbox") == ()


def test_for_workflow_and_workflows_of_are_the_two_directions():
    pools = PoolRegistry()
    local = pools.add(Pool("local", capacity=1))
    sandbox = pools.add(Pool("sandbox", capacity=3))
    pools.bind("build", "local")
    pools.bind("gamedev", "local")
    pools.bind("release", "sandbox")

    assert pools.for_workflow("build") is local
    assert pools.for_workflow("release") is sandbox
    assert pools.workflows_of("local") == ("build", "gamedev")
    assert pools.workflows_of(local) == ("build", "gamedev")
    assert pools.workflows_of(local.pool) == ("build", "gamedev")
    assert pools.workflows_of("sandbox") == ("release",)


def test_an_unbound_workflow_and_an_unknown_pool_are_lookup_errors():
    pools = PoolRegistry()
    pools.add(Pool("local", capacity=1))

    with pytest.raises(KeyError, match="not bound to a pool"):
        pools.for_workflow("build")
    with pytest.raises(KeyError, match="no pool named 'sandbox'"):
        pools.workflows_of("sandbox")
    with pytest.raises(KeyError, match="no pool named 'sandbox'"):
        pools.get("sandbox")
    assert pools.get("local").name == "local"


def test_pools_do_not_lend_capacity_to_each_other():
    pools = PoolRegistry()
    local = pools.add(Pool("local", capacity=1))
    sandbox = pools.add(Pool("sandbox", capacity=1))
    pools.bind("build", "local")
    pools.bind("release", "sandbox")

    local.try_acquire(1)

    assert local.try_acquire(2) is None
    assert sandbox.try_acquire(3) is not None
    assert pools.snapshot()["local"]["in_flight"] == 1
    assert pools.snapshot()["sandbox"]["in_flight"] == 1


# --- live registration: unbind and rebind (22 §Pools, T083) ----------------


def test_unbind_drops_the_binding_and_keeps_the_pool():
    pools = PoolRegistry()
    local = pools.add(Pool("local", capacity=1))
    pools.bind("build", "local")
    pools.bind("gamedev", "local")

    pools.unbind("build")

    assert pools.workflows_of("local") == ("gamedev",)
    assert "local" in pools and pools.get("local") is local
    with pytest.raises(KeyError, match="not bound to a pool"):
        pools.for_workflow("build")
    # The name is free again: a pool may now take it, and a bind may.
    assert pools.bind("build", "local") is local


def test_rebind_moves_the_binding_and_both_pools_follow():
    pools = PoolRegistry()
    pools.add(Pool("local", capacity=1))
    sandbox = pools.add(Pool("sandbox", capacity=1))
    pools.bind("build", "local")
    pools.bind("gamedev", "local")

    assert pools.rebind("build", "sandbox") is sandbox

    assert pools.for_workflow("build") is sandbox
    assert pools.workflows_of("local") == ("gamedev",)
    assert pools.workflows_of("sandbox") == ("build",)


def test_rebind_to_the_same_pool_is_a_no_op():
    pools = PoolRegistry()
    local = pools.add(Pool("local", capacity=1))
    pools.bind("build", "local")

    assert pools.rebind("build", "local") is local
    assert pools.workflows_of("local") == ("build",)


def test_unbind_and_rebind_are_lookups_and_fail_as_lookups():
    """``KeyError`` throughout: an unbound name, an unknown pool.

    ``bind``'s ``ValueError`` is for a registration that is wrong; the
    engine's ``ValueError`` is for a move with attempts in flight. The
    server has to tell "no such pool" from that refusal by type.
    """

    pools = PoolRegistry()
    pools.add(Pool("local", capacity=1))
    pools.bind("build", "local")

    with pytest.raises(KeyError, match="'release' is not bound"):
        pools.unbind("release")
    with pytest.raises(KeyError, match="'release' is not bound"):
        pools.rebind("release", "local")
    with pytest.raises(KeyError, match="no pool named 'sandbox'"):
        pools.rebind("build", "sandbox")
    # A refusal changes nothing.
    assert pools.workflows_of("local") == ("build",)
    assert "sandbox" not in pools
