# T009 — Event vocabulary and the `Event` model

**Task.** `docs/v1/17-serial-task-plan.md` § `### T009`.
**Specs.** `docs/v1/03-domain-model.md` §Event vocabulary (the complete
list of names — copy it exactly, it is the contract); `docs/v1/18-event-payloads.md`
(one payload model per name, field for field).

## What this task is

The names and the shapes. Every event the system will ever emit is
enumerated here, with a typed payload per name, before anything emits
one. Later tasks reference `EventName.x` and never a string literal.

## What this task is not

- **T013** writes the `EventBus` that publishes and persists. This task
  writes no bus, no subscribers, no store access.
- No SSE, no API, no TypeScript mirror. The wire and the SPA come later
  and generate from this, never in parallel with it.
- No new event names. If 03 and 18 disagree, stop and ask rather than
  inventing a reconciliation — the vocabulary is a contract two other
  documents cite.

## Steps

1. `athanore/events/names.py`:
   - `class EventName(StrEnum)` with every row of 03 §Event vocabulary,
     `run.created` through `engine.stopping`;
   - `PLUGIN_PREFIX = "plugin."`;
   - `is_known(name) -> bool` — an enum member, or
     `plugin.<workflow>.<name>` with two further identifier segments;
   - `EPHEMERAL = {EventName.task_stream}` (the events that are not
     retained);
   - `matches(pattern, name)` — `fnmatch` over dotted names where a `*`
     matches exactly **one** segment. `run.*` must not match `run.a.b`;
     that single rule is what the tests pin.
2. `athanore/events/payloads.py`: one pydantic model per name exactly as
   18 specifies, plus `EventEnvelope` with the discriminated union keyed
   on the name.
3. `athanore/events/model.py`: `class Event(BaseModel)` with `id: int |
   None`, `run_id: str | None`, `task_id: int | None`, `name: str`,
   `data: dict`, `created: datetime`.

## Verification

`tests/test_events_names.py` must cover:

- every enum value is `subject.verb` — iterate the enum, do not spot-check;
- `matches("task.*", "task.stream")` is true;
- `matches("run.*", "run.a.b")` is false;
- `is_known("plugin.gamedev.word")` is true, `is_known("plugin.x")` false;
- every name in 03 has a payload model, checked by iterating `EventName`
  against the union rather than by a hand-written list — a name added
  later without a payload should fail this test.

```sh
./scripts/dev.sh "uv run python -c \"
from athanore.events.names import EventName, matches, is_known
print(len(list(EventName)), 'names')
print(matches('run.*','run.a.b'), is_known('plugin.gamedev.word'))\""
```

## Done

- Tests pass; pyright clean.
- The enum has one member per row of 03, no more and no fewer.
- `**Status.** Done.` on `### T009`, in the same commit.

## Files

```
athanore/events/names.py
athanore/events/payloads.py
athanore/events/model.py
tests/test_events_names.py
docs/v1/17-serial-task-plan.md
```
