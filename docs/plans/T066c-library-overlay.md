# T066c — Workflow library overlay

**Task.** `docs/v1/17-serial-task-plan.md` § `### T066c`.
**Specs.** `docs/v1/10-frontend.md` §Library;
`docs/v1/15-decisions.md` D35; `docs/v1/08-api.md`
(`/api/workflows/{name}/source`).

## What this task is

Reading the workflow's actual source in the app — the thing that makes
"the signature is the graph" legible to someone who did not write it.

## What this task is not

- No editing. Read-only.
- No client-side parsing: the API returns source and per-node line
  ranges (T044).

## Steps

1. A left list: name, node count, run count, file.
2. A right-hand source viewer from `/api/workflows/{name}/source`, with
   shiki highlighting and per-node line anchors.
3. `open definition` from the graph pane (T063e) lands on that node's
   line.

## Verification

Vitest:

- selecting a workflow loads its source;
- the anchor scrolls to the right line — assert the scroll target, since
  "it rendered" is not the same as "it landed on the node".

## Done

- Tests pass.
- `**Status.** Done.` on `### T066c`, in the same commit.

## Files

```
web/src/overlays/Library.tsx
web/src/**/__tests__/**
docs/v1/17-serial-task-plan.md
```
