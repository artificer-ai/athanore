# T060 — SSE wrapper and invalidation table

**Task.** `docs/v1/17-serial-task-plan.md` § `### T060`.
**Specs.** `docs/v1/10-frontend.md` §Realtime (the invalidation table —
transcribe it, do not improvise); `docs/v1/08-api.md` §SSE (the server
half, T046).

## What this task is

The client side of realtime: one `EventSource`, a table mapping event
names onto query keys, and the reconnect behaviour that keeps a
long-lived tab honest.

## What this task is not

- No polling anywhere in the SPA. If a view is stale, its event is
  missing from the table.
- No per-component `EventSource`. One feed, fanned out.
- The stream handler **appends**; it does not refetch the transcript.

## Steps

1. `web/src/realtime/sse.ts`: `class EventFeed` over `EventSource`
   (`/api/events?after=<lastId>` plus `access_token` when auth is on —
   the one place a token legitimately rides in a query, because
   EventSource cannot set headers). Track `lastId` from frames that
   carry `id`; exponential reconnect 1 s → 30 s; emit
   `status: "open" | "reconnecting" | "down"`.
   On `resync`: clear `lastId` and `queryClient.invalidateQueries()`.
   On reconnect: refetch `/api/me`, and if `started_at` changed, refetch
   `/api/plugins` — the server restarted and its manifest may differ.
2. `web/src/realtime/invalidate.ts`: 10's table, with an
   **exact-then-glob** matcher (`task.stream` must never hit `task.*`,
   or every chunk invalidates the task list), and a coalescer batching
   keys in a 250 ms window.
3. The `stream` handler calls `appendStream(taskId, seqFrom)`, fetching
   `/api/tasks/{id}/stream?after=` and appending to the cache.
4. `registerRefreshOn(names, keys)` for plugin panels.
5. `ServerDownBanner` with a countdown; header counts greyed through a
   `data-down` attribute.

## Verification

Vitest:

- matcher precedence, with `task.stream` explicitly asserted against
  `task.*`;
- coalescing merges duplicate keys within the window;
- reconnect uses `after=lastId`;
- `resync` clears the cache and the id.

## Done

- Tests pass.
- `**Status.** Done.` on `### T060`, in the same commit.

## Files

```
web/src/realtime/{sse.ts,invalidate.ts}
web/src/components/ServerDownBanner.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
