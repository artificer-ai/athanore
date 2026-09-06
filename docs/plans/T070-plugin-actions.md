# T070 — Action execution endpoint and the `form` kind

**Task.** `docs/v1/17-serial-task-plan.md` § `### T070`.
**Specs.** `docs/v1/09-plugins.md` §Actions; `docs/v1/08-api.md`
§Plugins; `docs/v1/10-frontend.md` §Forms.

## What this task is

Making declared actions executable: one endpoint, the `form` panel kind
that calls it, and the confirm flow for destructive ones.

## What this task is not

- No new auth model — plugin routes are operator routes (T049a).
- No bypassing validation because the SPA already validated: the server
  validates with the action's model, every time.

## Steps

1. `POST /api/plugins/{wf}/actions/{name}`: validate `input` against the
   action model (T042's 422 shape), resolve the `PluginContext` from the
   action's `scope`, **404 a foreign run**, call the handler, map
   `PluginError → {status, error, code: "plugin_error"}`, return JSON.
2. SPA: the `form` panel kind renders `ActionForm(schema)` for the named
   action; `confirm=true` opens a confirmation dialog first; the result
   raises a toast.
3. Actions are listed in the palette under `plugin: <title>` (the
   section T066a left empty).

## Verification

Python: validation failures, scoping (including the foreign-run 404),
and `PluginError` mapping. Vitest: the confirm flow, including that
cancelling posts nothing.

```sh
./scripts/dev.sh "uv run scripts/dump_openapi.py && pnpm -C web gen"
git diff --exit-code tests/snapshots web/src/api/gen
```

## Done

- Tests pass; snapshot and client regenerated.
- `**Status.** Done.` on `### T070`, in the same commit.

## Files

```
athanore/plugins/mount.py
web/src/panes/kinds/Form.tsx
web/src/overlays/Palette.tsx
tests/plugins/test_actions.py
web/src/**/__tests__/**
tests/snapshots/openapi.json
docs/v1/17-serial-task-plan.md
```
