# T061 — Run list

**Task.** `docs/v1/17-serial-task-plan.md` § `### T061`.
**Specs.** `docs/v1/10-frontend.md` §Run list;
`docs/v1/design/Athanore.dc.html` (column template, spacing, the
selected-row treatment — match it).

## What this task is

The left half of the app: filter chips, a filter input, and the row grid
that is the primary way an operator finds anything.

## What this task is not

- No detail content (T062+).
- No server-side filtering. The filter is client-side over title and id;
  the API's `?status`/`?workflow` back the chips.
- No animation without cause: the header pulse runs **only** when there
  is something active.

## Steps

1. `RunList`: header chips (`all` plus one per workflow, accent-tinted
   when active); a `/` filter input; grid rows using the mock's column
   template — RUN (8-char id) · WORKFLOW · TITLE · STATUS pill · NODE
   (with `⚠` when `pending_requests > 0`) · AGE; zebra striping; the
   selected-row treatment (accent gradient, 2 px left border, inset
   glow); a footer strip reading `n shown · ↑↓ select · ⏎ focus detail`;
   and the collapsed rail `RUNS n`.
2. Selection writes `?run=` — the URL is the state.
3. Header: `n runs · ● k active`, pulsing only when `k > 0`.
4. `useRuns()` from the generated query options, invalidated by
   `run.*` / `task.*` through T060's table.

## Verification

Vitest:

- `⚠` appears exactly when `pending_requests > 0`;
- the filter narrows on both title and id;
- pill text and colour class per status, one case each — the status
  colours come from 10's table, so a wrong mapping is a spec deviation,
  not a preference.

Then live: submit a run from the CLI and watch the list update without a
reload. That is the task's Done condition and needs the server running.

## Done

- Tests pass; the live update observed.
- `**Status.** Done.` on `### T061`, in the same commit.

## Files

```
web/src/components/RunList/**
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
