# T049 — Plugin declarations, registry, manifest

**Task.** `docs/v1/17-serial-task-plan.md` § `### T049`.
**Specs.** `docs/v1/09-plugins.md` §Declarations and §Registration (the
six validation checks); `docs/v1/15-decisions.md` D50.

## What this task is

The declaration vocabulary a workflow uses to extend the UI and the API,
plus the registry that validates it and emits a manifest.

## What this task is not

- No mounting, no dispatch — T049a.
- **Not a fourth rule.** A plugin declaration is something declared on
  the workflow: an existing seam (`AGENTS.md` §Three rules only).
- `workflow.py` remains the only module importing both `graph` and
  `plugins.decl` — the layering contract T005 encoded.

## Steps

1. `athanore/plugins/decl.py`: `Route(path, methods, fn)`,
   `Action(name, title, scope, confirm, model, fn)`,
   `Panel(name, slot, placement, kind, scope, node, source, element,
   refresh_on)`, `Handler(event, fn)`, the `PanelKind` and `Slot` enums,
   and `PluginError(status, message)`.
2. Extend `Workflow` (T020) with `route()`, `action()`, `panel()`,
   `on()` and `assets=`.
3. `athanore/plugins/registry.py`: `collect(workflow) -> PluginSpec`;
   `validate(spec, graph, assets_root)` with **all six** checks of 09
   §Registration; `manifest_entry(spec) -> dict` where actions carry
   `model_json_schema()` and `plugin.*` handler names are checked
   against T009's `is_known`.

## Verification

`tests/plugins/test_registry.py`:

- each of the six validation errors, one test apiece — a validation
  suite that only tests the happy path is what lets a bad declaration
  reach the SPA;
- the manifest shape for a workflow declaring one of everything;
- `panel()` is a plain call returning the `Panel` (not a decorator) —
  the API detail that is easy to get backwards.

## Done

- Tests pass.
- `**Status.** Done.` on `### T049`, in the same commit.

## Files

```
athanore/plugins/{decl.py,registry.py}
athanore/workflow.py
tests/plugins/test_registry.py
docs/v1/17-serial-task-plan.md
```
