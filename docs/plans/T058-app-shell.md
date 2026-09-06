# T058 — App shell: router, client state, layout regions

**Task.** `docs/v1/17-serial-task-plan.md` § `### T058`.
**Specs.** `docs/v1/10-frontend.md` §Layout and §URL state;
`docs/v1/design/Athanore.dc.html` (the regions and copy).

## What this task is

The frame: one route whose search parameters hold all the UI state worth
sharing, a small persisted preference store, and four empty layout
regions.

## What this task is not

- No data fetching (T059) and no run content (T060+).
- No second route. The whole app is `/` plus validated search params —
  that is what makes every view linkable.
- No preference that belongs in the URL, and no URL state that belongs
  in preferences. `run`, `pane`, `overlay`, `task` are shareable; widths
  are personal.

## Steps

1. TanStack Router, one route `/`, with **validated** search:
   `{run?: string, pane?: number, overlay?: "palette"|"new"|"library"|
   "edit"|"keys"|"task"|"pick-retry"|"pick-move"|"pick-cancel"|
   "pick-rerun", task?: number}`. An invalid `?overlay=` is **dropped,
   not thrown** — a stale bookmark must not white-screen the app.
2. zustand `usePrefs` (persisted: `listWidth`, `listCollapsed`,
   `autoSwitchOnRequest`, `notifications`, `token`) and `useUi`
   (transient: focus region).
3. Layout: `Header` (brand mark, `__APP_VERSION__` injected
   from `pyproject.toml` at build time, count placeholders), `RunList`
   (empty), `Detail` (empty pane bar), `Footer` (key chips).

## Verification

Vitest:

- search-param round-trip for each key;
- prefs persist to `localStorage` and survive a reload;
- an invalid `?overlay=` is dropped rather than throwing.

```sh
docker compose --profile web up web       # Vite on :5173, /api proxied to 4002
./scripts/dev.sh "pnpm -C web build"
```

Then serve the built output through `athanore serve` and confirm the
shell renders — the built path and the dev path are different enough to
be worth checking both.

## Done

- Tests pass; `pnpm build` output served by `athanore serve` shows the
  shell.
- `**Status.** Done.` on `### T058`, in the same commit.

## Files

```
web/src/routes/**
web/src/store/{prefs.ts,ui.ts}
web/src/components/{Header,RunList,Detail,Footer}.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
