# T010 — Domain enums and read models

**Task.** `docs/v1/17-serial-task-plan.md` § `### T010`.
**Specs.** `docs/v1/03-domain-model.md` (the statuses and their
meanings); `docs/v1/07-storage.md` §Schema (the columns these rows
mirror); `docs/v1/12-security.md` §Task tokens (why `token_hash` is
excluded).

## What this task is

One module of frozen pydantic read models and the enums they use. No
I/O: this is the vocabulary the repositories will return.

## What this task is not

- **T011** writes the SQLAlchemy tables. These models mirror that schema
  but do not import it, and there is no ORM anywhere in this build.
- **T014 onward** write the repositories that construct these rows.
- No serialization helpers for the API — `api/schemas` is T030's.

## Steps

1. The enums, values exactly as the task lists them: `RunStatus`,
   `TaskStatus`, `LogAuthor`, `LogKind`, `ChunkKind`, `RequestMode`,
   `RequestSource`, `RequestKind`, `AnswerAuthor`. `StrEnum` throughout
   (`AGENTS.md` §Conventions: statuses are enums on both sides).
2. The read models, all `model_config = ConfigDict(frozen=True)`:
   `RunRow`, `TaskRow`, `LogEntryRow`, `SubmissionRow`,
   `StreamChunkRow`, `RequestRow`, `AnswerRow`, `EventRow`,
   `RunSummary` (adds `current_nodes: list[str]`, `pending_requests:
   int`, `unregistered: bool`), `RunStats` (`input_tokens`,
   `output_tokens`, `total_tokens`, `cost`, `tool_calls`, `duration_s`,
   every one optional).
3. **`TaskRow` carries no token.** It holds `token_hash`, declared
   `Field(exclude=True)` so it never appears in `model_dump()`. This is
   the "task tokens are header-only and never appear in operator
   responses" rule made structural — the API cannot leak what the model
   will not serialize.
4. `RunStats` fields are optional because unknown is omitted, never
   zero-filled (`AGENTS.md` §Architecture rules, real data only). Do not
   give them `0` defaults.

## Verification

```sh
./scripts/dev.sh "uv run pyright"     # strict on athanore/store
./scripts/dev.sh "uv run python -c \"
from athanore.store.rows import TaskRow, RunStats
t = TaskRow(...)                      # fill with plausible values
assert 'token_hash' not in t.model_dump()
assert RunStats().model_dump(exclude_none=True) == {}\""
```

The two assertions above are the ones worth a test even though the task
lists none: a `token_hash` that serializes is a security defect, and a
`RunStats` that zero-fills is a lie about token counts.

## Done

- Importable, pyright strict clean.
- `token_hash` absent from `model_dump()`; `RunStats` omits unknowns.
- `**Status.** Done.` on `### T010`, in the same commit.

## Files

```
athanore/store/rows.py
docs/v1/17-serial-task-plan.md
```
