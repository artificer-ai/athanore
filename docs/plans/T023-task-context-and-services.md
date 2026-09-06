# T023 — `TaskContext`, `current_task()`, `TaskServices`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T023`.
**Specs.** `docs/v1/04-engine.md` §TaskContext (the field list);
`AGENTS.md` §Architecture rules — "agents reach the store only through
`TaskContext`".

## What this task is

The object a node body sees, and the service bundle hanging off it. This
is the seam the whole "new capability attaches to an existing seam" rule
depends on, so its shape matters more than its size.

## What this task is not

- **No request implementation.** `requests: RequestsPort` is a
  `Protocol`; T032 provides the implementation.
- **No stream service** — T023a, immediately after. `stream` is `None`
  until then.
- `lease.released()` is T026's. A `NotImplementedError` stub here is
  what the task asks for and is not a quality-bar violation — but it
  must raise, never return a plausible lie.
- No agent code. T027 onward build on this.

## Steps

1. `engine/context.py`: `@dataclass class TaskContext` with 04's fields
   plus private `_timeout: asyncio.Timeout | None` and `_released_at:
   float | None`; `_current: ContextVar[TaskContext | None]`;
   `bind(ctx)` context manager; `current_task()` raising
   `RuntimeError("no task context")`; `maybe_current_task()`.
   Nested binds must restore the outer context on exit — a fan-out that
   loses its context is unfixable later.
2. `engine/services.py`: `class TaskServices` bundling
   - `log: LogService` — `append(text, *, author="agent", kind=None)`,
     one uow, emits `log.appended`;
   - `submissions: SubmissionService` — `latest()`, `accept(payload)`
     (insert + `submission.accepted`), `reject(errors, schema)` (event
     only, no row);
   - `requests: RequestsPort` (Protocol);
   - `run: RunService` — `get()`;
   - `lease: LeaseService` — `released()`, stubbed to raise until T026;
   - `events: EventPort` — `publish(name, data)` **restricted to
     `plugin.*` names**, so user land cannot forge `task.done`;
   - `stream` — `None` until T023a.

## Verification

`tests/engine/test_context.py`:

- `current_task()` raises outside `bind`;
- nested binds restore the outer context;
- `TaskServices.log.append` writes a row and emits `log.appended`
  carrying the task id;
- `events.publish("task.done", …)` is rejected — the security-shaped
  test in this task, so write it as an assertion on the raised error,
  not just on absence.

## Done

- Tests pass; pyright strict clean on `athanore/engine`.
- `**Status.** Done.` on `### T023`, in the same commit.

## Files

```
athanore/engine/context.py
athanore/engine/services.py
tests/engine/test_context.py
docs/v1/17-serial-task-plan.md
```
