# T063b — Log renderer

**Task.** `docs/v1/17-serial-task-plan.md` § `### T063b`.
**Specs.** `docs/v1/10-frontend.md` §Panes (the tone mapping);
`docs/v1/08-api.md` §Runs (`POST /runs/{id}/log`).

## What this task is

The event log pane: work-log entries and lifecycle events merged by
time, plus the composer that lets an operator leave a note.

## What this task is not

- No client-side log storage. The merge happens per render from the
  builtin log source (T050).
- No markdown for engine lines — only agent and user entries render
  markdown, so an engine message cannot smuggle formatting.

## Steps

1. Header: `EVENT LOG · n lines · ● tailing / ○ complete`.
2. Rows `time · source · message`, merged from the work log and
   lifecycle events with 10's tone mapping.
3. The composer (`l`) posting `/api/runs/{id}/log`, clearing on success.
4. A `?node=` filter — the graph pane (T063e) links into it.

## Verification

Vitest:

- merge order by time across both sources;
- tone classes per kind;
- the composer posts and clears, and does **not** clear on a failed
  post;
- `?node=` filters the rows.

## Done

- Tests pass.
- `**Status.** Done.` on `### T063b`, in the same commit.

## Files

```
web/src/panes/kinds/Log.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
