# T049a — Plugin mount, `PluginContext` dependency, `on` dispatch

**Task.** `docs/v1/17-serial-task-plan.md` § `### T049a`.
**Specs.** `docs/v1/09-plugins.md` §Context and scopes, §Mounting;
`docs/v1/12-security.md` §Plugins.

## What this task is

Turning declarations into live routes, giving each a context scoped to
what it asked for, and dispatching event handlers **after** commit.

## What this task is not

- No builtin plugins — T050 onward.
- Plugin routes are **operator** routes: `Depends(operator_auth)`. A
  plugin does not get its own auth model.
- A plugin handler must never be able to break the engine.

## Steps

1. `athanore/plugins/context.py`: `PluginContext` dataclass (`run_id`,
   `task_id`, `node`, `workflow`, `run`, `task`, `services`, `ops`) with
   09's scope rules — a `workflow` or `global` context has **no run**,
   and only run-independent services. Reaching for a run-scoped service
   from a global context raises `PluginError(400)` rather than returning
   `None` and failing later somewhere confusing.
2. `athanore/plugins/mount.py`: `mount(app, spec)` building an
   `APIRouter(prefix=f"/api/plugins/{wf}")` with `Depends(operator_auth)`;
   the `PluginContext` dependency resolves the `run_id` / `task_id` /
   `node` query params and **404s a run belonging to another workflow**.
3. `GET /api/plugins` — the manifest, builtins first, under the
   `_builtin` workflow.
4. `dispatch_handlers(bus, specs)`: subscribe once, call matching `on`
   handlers **after commit**, and log exceptions. A raising handler is
   logged and dropped; it does not fail the transaction that triggered
   it, and it does not stop other handlers.

## Verification

`tests/plugins/test_mount.py`:

- a route resolves its context;
- a foreign `run_id` → 404;
- a `global` route gets `run=None`, and `services.log` raises
  `PluginError(400)`;
- an `on` handler receives `run.completed`;
- **a raising handler does not affect the engine** — assert the run
  still completes and other handlers still fire;
- the manifest endpoint's shape.

## Done

- Tests pass; snapshot updated.
- `**Status.** Done.` on `### T049a`, in the same commit.

## Files

```
athanore/plugins/{context.py,mount.py}
athanore/api/app.py
tests/plugins/test_mount.py
tests/snapshots/openapi.json
docs/v1/17-serial-task-plan.md
```
