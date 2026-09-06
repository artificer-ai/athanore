# T013 — `EventBus`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T013`.
**Specs.** `docs/v1/03-domain-model.md` §Event vocabulary (T009 already
encoded it); `docs/v1/08-api.md` §SSE (what `overflowed` is for).

## What this task is

In-process fan-out. One class, no persistence: the bus delivers to
subscribers, and T013a's `UnitOfWork` is what makes an event durable
before it ever reaches here.

## What this task is not

- No storage. `publish` writes nothing to the database.
- No SSE endpoint (T044) and no HTTP anything.
- **`publish` never awaits a subscriber.** A slow SSE client must not be
  able to stall a transaction commit; that is the whole reason the
  subscription owns a bounded queue and drops on overflow.

## Steps

1. `subscribe(patterns: list[str] | None = None, *, maxsize=1000) ->
   Subscription` — a `Subscription` wraps an `asyncio.Queue` and a
   `close()`. Patterns are matched with `names.matches`, so `run.*` is
   one segment (T009's rule).
2. On a **full** queue: set `sub.overflowed = True` and drop the event.
   Do not block, do not grow the queue. The flag is how T044's SSE
   endpoint knows to tell the client to `resync` instead of pretending
   it has a complete stream.
3. `publish(event)` — fan out to matching subscriptions, synchronously
   and without awaiting.
4. `async def wait_for(pattern, predicate, timeout) -> Event` — the
   convenience the tests and later waiters use.

## Verification

`tests/events/test_bus.py`:

- a subscriber on `["run.*"]` receives `run.created` and not
  `task.started`;
- with `maxsize=1` and two events published, `overflowed` is true and
  the queue holds one;
- after `close()`, no further delivery;
- `wait_for` returns the first matching event, and raises
  `TimeoutError` when nothing matches in time.

Prove the non-blocking property explicitly: publish to a subscriber
that never drains, with the queue full, and assert `publish` returns
without awaiting — a test that would hang if someone later "fixes" the
drop by blocking.

## Done

- Tests pass; pyright clean.
- `**Status.** Done.` on `### T013`, in the same commit.

## Files

```
athanore/events/bus.py
tests/events/test_bus.py
docs/v1/17-serial-task-plan.md
```
