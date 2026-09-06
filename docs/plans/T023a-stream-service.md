# T023a — `StreamService` flusher

**Task.** `docs/v1/17-serial-task-plan.md` § `### T023a`.
**Specs.** `docs/v1/07-storage.md` §Transcript writes;
`docs/v1/02-architecture.md` §Configuration (`stream_flush_interval`).

## What this task is

Batching for agent output: a node's stream chunks accumulate in memory
and land as one insert per interval, with an ephemeral event announcing
the range.

## What this task is not

- No SSE endpoint (T044) and no agent wiring (T027+).
- The `task.stream` event is **ephemeral** — `publish_ephemeral`, never
  the outbox, never a row in `events` (T009's `EPHEMERAL`).
- No backpressure onto the node body. A flush failure must not surface
  inside `await agent.run()`.

## Steps

1. `StreamService` in `services.py`: an in-memory `buffer: list[(seq,
   kind, text)]`, a `seq` counter **initialised from
   `StreamRepo.last_seq`** so a restarted task continues rather than
   colliding with its own history, and `append(kind, text)`.
2. A background `_flusher()` on `stream_flush_interval`: when the buffer
   is non-empty, one `uow.stream.append_batch`, then
   `store.publish_ephemeral(Event("task.stream", data={seq_from,
   seq_to}))`.
3. `async def close()` cancels the flusher and flushes once more —
   the last chunks of a finished agent turn are the ones a reader most
   wants.
4. A flush failure is logged and retried next tick, never raised into
   the body.

## Verification

`tests/engine/test_stream.py`:

- 20 appends inside one interval → **one** batch insert and **one**
  ephemeral event;
- `close()` flushes the remainder;
- seq continues after a restart, via `last_seq`;
- the ephemeral event never appears in the `events` table;
- a failing flush (patch the repo to raise once) does not propagate, and
  the next tick succeeds.

## Done

- Tests pass, including the failure-swallowing one.
- `**Status.** Done.` on `### T023a`, in the same commit.

## Files

```
athanore/engine/services.py
tests/engine/test_stream.py
docs/v1/17-serial-task-plan.md
```
