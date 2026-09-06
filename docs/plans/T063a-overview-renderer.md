# T063a — Overview renderer

**Task.** `docs/v1/17-serial-task-plan.md` § `### T063a`.
**Specs.** `docs/v1/10-frontend.md` §Panes (field sources);
`docs/v1/design/Athanore.dc.html` (the layout being reproduced).

## What this task is

The run's dashboard pane: four metric tiles, per-node token bars, a
key/value block, the node table, and outputs.

## What this task is not

- No new API. Everything comes from `RunDetail` and the builtin
  overview source (T050).
- **Never zero-fill.** SESSION is omitted when no agent ran; a metric
  with no data shows as absent, not `0` (`AGENTS.md` real data only).
- No editing; this pane is read-only.

## Steps

1. `MetricGrid` — TOKENS, COST, DURATION, POSITION.
2. Per-node token bars: accent for the active node, accent-700 for the
   rest, scaled to the largest node.
3. The `kv` meta block — RUN, WORKFLOW, TITLE, STATUS · node, AGE,
   SESSION, AGENTS, DESCRIPTION, with the sources 10 §Panes names.
4. The NODES zebra table — NODE · ATT · STATUS · TOKENS · DUR, each row
   opening the task drawer.
5. An OUTPUTS list **only** when the run had more than one terminal
   branch.
6. `placement=card` panels appended.

## Verification

Vitest against a `RunDetail` fixture:

- tiles and bars;
- the kv fields, including SESSION **omitted** when no agent ran;
- OUTPUTS shown only for multi-branch runs;
- a run with no stats renders without `0`s or `NaN`.

## Done

- Tests pass.
- `**Status.** Done.` on `### T063a`, in the same commit.

## Files

```
web/src/panes/kinds/Overview.tsx
web/src/components/MetricGrid.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
