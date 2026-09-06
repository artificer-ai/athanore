# T063e — Graph rail renderer

**Task.** `docs/v1/17-serial-task-plan.md` § `### T063e`.
**Specs.** `docs/v1/10-frontend.md` §Graph rail;
`docs/v1/08-api.md` §Graph semantics (the data);
`docs/v1/15-decisions.md` D32, D62.

## What this task is

The run's shape as a vertical rail: nodes in generation order, branches
indented, joins closing them, loops drawn on a right-hand rail.

## What this task is not

- No graph library and no canvas. It is rows and rails.
- No layout computation the API already did — `/graph` gives
  generations, branches, arrivals and edge kinds.
- No moving a task into a join: the menu item is disabled, matching
  T024c's `Conflict`.

## Steps

1. From `/api/runs/{id}/graph`: nodes in generation order; glyphs
   `✓ ● ✗ ·`, and `⋈` for joins.
2. A detail column: tokens · duration, or `attempt n · elapsed`, or
   `waiting`, or `k of n arrived`.
3. `▼` connectors for forward edges; `▲` from branch sub-lists into
   their join; a right-hand rail with `◀` and a `loop` label for back
   edges.
4. Fan-out branches as indented sub-lists keyed by
   `branches[].from_task`, closed at the join.
5. An EDGES legend (edge / loop / join / gate), the SOURCE path, and
   `open definition` opening the library overlay.
6. Click → the log pane filtered to that node; right-click → rerun /
   move, with move disabled on joins.

## Verification

Vitest against **three** fixtures — linear with a loop-back, fan-out
without a join, fan-out closed by a join:

- row order;
- the rails;
- sub-list nesting;
- the `k of n` text.

Then the task's real Done: all five panes rendering `feature_build` and
`gamedev` runs produced on `FakeACPAgent`. Run them and look.

## Done

- Tests pass; both example runs render across all five panes.
- `**Status.** Done.` on `### T063e`, in the same commit.

## Files

```
web/src/panes/kinds/GraphRail.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
