"""In-process fan-out of the event vocabulary.

One :class:`EventBus` per process (D29). It is the *notification* half of
the story only: durability belongs to the store's outbox, which inserts
an event and commits before it ever hands it here. Nothing published by
this module is stored, and a crash between the commit and the fan-out
costs a subscriber a wake-up, not a row — SSE clients resync from the
store by cursor (07 §Unit of work and outbox).

The load-bearing property is that :meth:`EventBus.publish` is a plain
function that never awaits a subscriber. A commit runs inside the store's
writer lock, so an SSE client that has stopped reading its socket would
otherwise stall every writer in the process. Each subscription therefore
owns a bounded queue and a subscription that cannot keep up **loses
events**: the bus sets :attr:`Subscription.overflowed` and drops, and the
SSE endpoint turns that flag into a ``resync`` frame (08 §Events) rather
than pretending it delivered a complete stream.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from athanore.events import names
from athanore.events.model import Event

#: Depth of a subscription's queue unless the subscriber asks for another.
#: Deep enough that a subscriber which is merely slow catches up, shallow
#: enough that one which has stopped reading is bounded memory.
DEFAULT_MAXSIZE = 1000


class Subscription:
    """One subscriber's bounded view of the bus.

    Read it by awaiting ``queue.get()``. Check :attr:`overflowed` whenever
    you have drained it: it is set — and stays set — as soon as the bus
    has dropped an event for this subscription, and it is the only
    signal that the stream has a hole in it.

    A subscription must be closed when its reader goes away; the bus
    holds a reference until it is, and would keep filling its queue.
    """

    def __init__(
        self,
        bus: EventBus,
        patterns: tuple[str, ...] | None,
        maxsize: int,
    ) -> None:
        self._bus = bus
        #: The globs this subscription selects, or ``None`` for everything.
        self.patterns = patterns
        #: Events delivered to this subscriber, oldest first.
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        #: Has the bus dropped an event because :attr:`queue` was full?
        self.overflowed = False
        #: Has :meth:`close` been called?
        self.closed = False

    def matches(self, name: str) -> bool:
        """Does this subscription select the event called ``name``?

        A subscription with no patterns selects everything; otherwise a
        name is selected when any pattern matches it segment by segment
        (:func:`athanore.events.names.matches`), so ``run.*`` takes
        ``run.created`` and leaves ``task.started``.
        """
        if self.patterns is None:
            return True
        return any(names.matches(pattern, name) for pattern in self.patterns)

    def close(self) -> None:
        """Stop delivery and drop the bus's reference. Idempotent."""
        if self.closed:
            return
        self.closed = True
        self._bus._detach(self)


class EventBus:
    """Publish/subscribe over :class:`~athanore.events.model.Event`."""

    def __init__(self) -> None:
        self._subscriptions: list[Subscription] = []

    @property
    def subscriptions(self) -> tuple[Subscription, ...]:
        """The live subscriptions, in the order :meth:`publish` fans out."""
        return tuple(self._subscriptions)

    def subscribe(
        self,
        patterns: list[str] | None = None,
        *,
        maxsize: int = DEFAULT_MAXSIZE,
    ) -> Subscription:
        """A new subscription selecting ``patterns`` (all events if ``None``).

        Subscribe *before* reading whatever state you are catching up on:
        the store commits and then publishes, so a subscription taken
        first can only ever see an event twice, never miss one (06
        §Service, the missed-wake guard).
        """
        selected = None if patterns is None else tuple(patterns)
        subscription = Subscription(self, selected, maxsize)
        self._subscriptions.append(subscription)
        return subscription

    def publish(self, event: Event) -> None:
        """Fan ``event`` out to every matching subscription, without awaiting.

        Delivery is a non-blocking put per subscription: a full queue sets
        that subscription's :attr:`~Subscription.overflowed` flag and the
        event is dropped for it alone. Nothing here can suspend, so the
        transaction that emitted the event is never held open by a
        subscriber, and one stalled reader cannot starve another.
        """
        for subscription in tuple(self._subscriptions):
            if subscription.closed or not subscription.matches(event.name):
                continue
            try:
                subscription.queue.put_nowait(event)
            except asyncio.QueueFull:
                subscription.overflowed = True

    async def wait_for(
        self,
        pattern: str,
        predicate: Callable[[Event], bool] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109 - see the docstring
    ) -> Event:
        """The first event matching ``pattern`` that ``predicate`` accepts.

        Raises :exc:`TimeoutError` when ``timeout`` elapses first; a
        ``timeout`` of ``None`` waits indefinitely. The subscription is
        taken before the first await and closed on every exit, so a
        caller cannot leak one by being cancelled.

        ASYNC109 would have the caller wrap the call in
        :func:`asyncio.timeout` instead; this *is* that wrapper, and a
        waiter that has to spell the timeout itself is the convenience
        the method exists to remove.
        """
        subscription = self.subscribe([pattern])
        try:
            async with asyncio.timeout(timeout):
                while True:
                    event = await subscription.queue.get()
                    if predicate is None or predicate(event):
                        return event
        finally:
            subscription.close()

    def _detach(self, subscription: Subscription) -> None:
        """Forget ``subscription``.

        Called by :meth:`Subscription.close`, which is the only caller and
        which guards against a second call, so the subscription is always
        still registered here.
        """
        self._subscriptions.remove(subscription)


__all__ = ["DEFAULT_MAXSIZE", "EventBus", "Subscription"]
