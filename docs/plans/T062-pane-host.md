# T062 — Pane host: `usePanes`, `PaneBar`, index rules

**Task.** `docs/v1/17-serial-task-plan.md` § `### T062`.
**Specs.** `docs/v1/10-frontend.md` §Panes; `docs/v1/09-plugins.md`
§Panels (slots, placement, node scoping).

## What this task is

Which panes exist for the current selection, in what order, and how the
index behaves as the selection changes.

## What this task is not

- No rendering of pane contents — T062a.
- No keyboard wiring (T067). Expose the actions; bind them later.
- Panes are not hard-coded: the builtins come through the manifest like
  everything else (T050).

## Steps

1. `usePanes(runId)`: from `/api/plugins` — builtins first, then the
   selected run's workflow panels with `slot=run, placement=pane`.
   A node-slot panel appears **only while `/api/runs/{id}/graph` reports
   that node `live`**. With no run selected, the `global` panes.
2. `PaneBar`: collapse toggle, `◀ PANE (i/n) ▶`, the dots (a styled
   `RadioGroup`, 14×3: accent for current, accent-800 for plugin,
   neutral-800 for builtin), `run <id>`, and the status pill.
3. Index rules: persists across selection changes, **clamps** to the
   pane count, `←`/`→` wrap, `1`–`9` jump.

## Verification

Vitest:

- pane order for a workflow with two plugin panes;
- a node-slot pane appears only while that node is live;
- the index clamps when the new selection has fewer panes — the bug you
  get for free if you keep the index and forget the clamp;
- cycling wraps;
- the global panes show with no run selected.

## Done

- Tests pass.
- `**Status.** Done.` on `### T062`, in the same commit.

## Files

```
web/src/panes/{usePanes.ts,PaneBar.tsx}
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
