# T062a — `PaneRenderer` kinds

**Task.** `docs/v1/17-serial-task-plan.md` § `### T062a`.
**Specs.** `docs/v1/09-plugins.md` §Panel kinds (each kind's data shape
and sample); `docs/v1/10-frontend.md` §Panes.

## What this task is

One component that renders any panel kind from its declared `source`
data — the thing that makes the plugin system visible.

## What this task is not

- No `form` (T070) and no `custom` elements (T071): both are
  placeholders here, and a placeholder is correct **only** because the
  task says so and the real thing has a named task.
- No chart library. A tiny inline SVG line/bar.
- An unknown kind renders a placeholder card and **must not throw** — a
  plugin from a newer version must degrade, not white-screen the app.

## Steps

1. `PaneRenderer` switching on `kind`:
   - `markdown` — react-markdown + gfm, shiki lazily loaded;
   - `kv` — a two-column `dl`;
   - `table` — shadcn `Table` with click-to-sort;
   - `log` — an autoscroll list via `@tanstack/react-virtual` with a
     sticky "tailing" toggle;
   - `chart` — inline SVG;
   - `dashboard` — note, `MetricGrid`, table;
   - `form`, `custom` — placeholders;
   - unknown — placeholder card.
2. Panel data through `useQuery` on the panel's `source` path with
   `run_id` / `task_id` / `node` params; `refresh_on` registered in
   T060's invalidation table.

## Verification

Vitest:

- each kind renders **09's sample data** — use the document's samples,
  not invented ones, so the renderer and the spec cannot drift;
- an unknown kind renders the placeholder without throwing;
- `refresh_on` registers the right query key;
- a `source` returning 500 renders an error card rather than an empty
  pane.

Then look at it: the overview and log panes rendering from the builtin
sources is the task's Done condition.

## Done

- Tests pass; overview and log panes render live.
- `**Status.** Done.` on `### T062a`, in the same commit.

## Files

```
web/src/panes/PaneRenderer.tsx
web/src/panes/kinds/**
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
