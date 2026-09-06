# T020 — `Workflow` object

**Task.** `docs/v1/17-serial-task-plan.md` § `### T020`.
**Specs.** `docs/v1/04-engine.md` §Programmatic host;
`docs/v1/15-decisions.md` D48; `docs/v1/14-migration-and-phasing.md`
§Compatibility (the alias policy).

## What this task is

The user-facing object. `Workflow` owns a `GraphBuilder` and, from T049,
the plugin declarations — the one module allowed to import both `graph`
and `plugins.decl` (`AGENTS.md` §Layering).

## What this task is not

- No plugin declarations yet (T049). The seam exists; nothing fills it.
- `run(**settings)` is a **shorthand that imports `Server` lazily** —
  the real implementation is T031's. A lazy import here is not a stub;
  eagerly importing a server that does not exist is a broken module.
- Do not remove `AthanoreWorkflow`. It stays in `graph/__init__.py` as
  the deprecated alias.

## Steps

1. `athanore/workflow.py`: `class Workflow` wrapping a `GraphBuilder`:
   - `node(...)` delegating with the full T019 option set;
   - `finalize() -> Graph`, idempotent and cached — the same `Graph`
     object on the second call, not an equal one;
   - `graph` property raising if not finalized;
   - `name`;
   - `run(**settings)` shorthand, importing `Server` inside the method.
2. `AthanoreWorkflow = Workflow` kept in `graph/__init__.py` as the
   deprecated alias (14 §Compatibility). T003's `workflow.py` alias line
   is replaced by the real class here.

## Verification

`tests/test_workflow.py`:

- `finalize()` twice returns the *same* `Graph` (`is`, not `==`);
- node options round-trip through `Workflow.node(...)` to `Graph`;
- `graph` before `finalize()` raises;
- importing `athanore.workflow` does not import a server module —
  assert on `sys.modules` after a fresh import, since a lazy import that
  quietly became eager is exactly the regression this catches.

## Done

- Tests pass; pyright clean.
- `**Status.** Done.` on `### T020`, in the same commit.

## Files

```
athanore/workflow.py
athanore/graph/__init__.py
tests/test_workflow.py
docs/v1/17-serial-task-plan.md
```
