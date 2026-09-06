# T046 — SSE endpoint

**Task.** `docs/v1/17-serial-task-plan.md` § `### T046`.
**Specs.** `docs/v1/08-api.md` §SSE (replay, cap, resync);
`docs/v1/02-architecture.md` §Configuration (`sse_replay_cap`).

## What this task is

One stream that gives a client its missed history and then live events,
with no gap and no duplicate across the boundary. Everything hard about
this endpoint is that boundary.

## What this task is not

- No polling fallback, no per-run sockets.
- Not a durable queue: `task.stream` frames are ephemeral, carry **no
  `id`**, and are never replayed.

## Steps

1. `GET /api/events` → `EventSourceResponse(generator, ping=15)`.
2. In the generator: parse `after` (or `Last-Event-ID`), `run`, and
   `names` (comma-separated globs). **Subscribe before replaying.**
   Subscribing after the replay read is the missed-wake bug in its
   second form, and it costs a client every event in between.
3. Replay `events.list_after(after, limit=cap+1)` filtered by run and
   names. If the result exceeds the cap: yield `event: resync`, stop
   replaying, and continue live — the client refetches rather than
   receiving a truncated history it thinks is complete.
4. Track `last_id`; in the live loop drop anything with `id <= last_id`
   (the de-duplication across the boundary), yield
   `{"id": e.id, "event": e.name, "data": json}` for stored events, and
   `{"event": "task.stream", "data": …}` **without an `id`** for
   ephemeral ones.
5. On `sub.overflowed` (T013's flag) yield `resync`.
6. Set `X-Accel-Buffering: no`, and close the subscription on
   disconnect.

## Verification

`tests/api/test_sse.py`:

- replay then live in a single stream;
- **no duplicate across the replay/live boundary** — publish events
  while the replay is in flight;
- `names=run.*` filters;
- `task.stream` frames lack `id:`;
- the cap exceeded → `resync`;
- `access_token` accepted when auth is on (T043's one query-param
  exception).

## Done

- Tests pass, including the boundary test.
- `**Status.** Done.` on `### T046`, in the same commit.

## Files

```
athanore/api/sse.py
tests/api/test_sse.py
docs/v1/17-serial-task-plan.md
```
