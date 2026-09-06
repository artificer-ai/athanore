"""The registry of in-flight task contexts (T022).

`TaskContext` arrives in T023, so the stand-in here is what the registry
actually asks for: an object with a `task_id`. That is the point of the
protocol — the registry is done before the context exists.
"""

from dataclasses import dataclass

import pytest

from athanore.engine.live import LiveRegistry


@dataclass
class Ctx:
    """The whole of what `LiveRegistry` needs of a context."""

    task_id: int


def test_a_registered_context_is_findable_by_task_id():
    live = LiveRegistry()
    ctx = Ctx(7)

    live.register(ctx)

    assert live.context_for(7) is ctx
    assert 7 in live
    assert len(live) == 1


def test_an_unknown_task_has_no_context():
    live = LiveRegistry()
    assert live.context_for(99) is None
    assert 99 not in live
    assert live.all() == []


def test_unregister_returns_the_context_and_is_idempotent():
    live = LiveRegistry()
    ctx = Ctx(1)
    live.register(ctx)

    assert live.unregister(1) is ctx
    assert live.unregister(1) is None  # the runner's `finally`, twice
    assert live.context_for(1) is None
    assert len(live) == 0


def test_registering_one_task_twice_is_a_defect():
    live = LiveRegistry()
    live.register(Ctx(1))

    with pytest.raises(ValueError, match="already has a live context"):
        live.register(Ctx(1))


def test_a_task_can_be_registered_again_after_it_is_unregistered():
    live = LiveRegistry()
    first = Ctx(1)
    second = Ctx(1)

    live.register(first)
    live.unregister(1)
    live.register(second)

    assert live.context_for(1) is second


def test_all_is_a_copy_in_registration_order():
    live = LiveRegistry()
    contexts = [Ctx(n) for n in range(3)]
    for ctx in contexts:
        live.register(ctx)

    listed = live.all()

    assert listed == contexts
    for ctx in listed:  # cancelling an attempt unregisters it mid-iteration
        live.unregister(ctx.task_id)
    assert live.all() == []
    assert len(listed) == 3


def test_repr_says_how_many_are_live():
    live = LiveRegistry()
    live.register(Ctx(1))
    assert repr(live) == "LiveRegistry(1 live)"
