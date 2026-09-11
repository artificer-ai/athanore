# T084 — Live plugin mounting

**Task.** `docs/v1/17-serial-task-plan.md` § `### T084`.
**Specs.** `docs/v1/22-live-registration.md` §Live mounting, §SPA (the
`?v=` the notice depends on); `docs/v1/09-plugins.md` §Mounting (one
router per workflow, the manifest's order, one subscription, "a plugin
cannot break the engine"), §Wire contract, §Escape hatch (asset URLs);
`docs/v1/08-api.md` §Static (the SPA fallback is a fallback so that
later routes match first); D29 (the bus never awaits a subscriber),
D183 (the asset surface), D225 (no re-injection; the notice).

## What this task is

The plugin host's half: a workflow's routes, assets, manifest entry and
`on` handlers can be added to and removed from an application that is
already serving. It changes how `create_app` *holds* the specs and how
the routes that read them find them; it adds no verb anyone outside
the package calls yet — T085's `Server.add/replace/remove` are the
callers.

1. **`MountedPlugins`** (`athanore/plugins/mount.py`), constructed by
   `create_app` from the sequence it is given and stored as
   `app.state.plugins`. It holds the specs in order — builtins first,
   then registration order, the partition `mount_manifest` already
   applies made structural — the application, the settings (for
   `mount_plugin_assets`), and the `HandlerDispatch`. Its surface:
   `specs: tuple[PluginSpec, ...]` (a snapshot, per request),
   `add(spec)`, `remove(workflow) -> PluginSpec | None`,
   `replace(spec)`, `get(workflow)`. `__iter__`/`__len__` so the
   existing readers that loop `app.state.plugins` keep working
   unchanged where they do not need more.
2. **`add(spec)`**: `mount(app, spec)` as today (the router is included
   into the running app — Starlette matches `app.router.routes` on
   every request); `mount_plugin_assets(app, workflow, dir, settings)`
   when the spec has an assets directory; the spec is appended;
   `dispatch.set(workflow, spec)`; `app.openapi_schema = None`. A spec
   that declares nothing (empty `spec`) is recorded but mounts no
   router, as `Server.register` decides today — keep that decision
   where it is, and let `MountedPlugins` accept an empty spec so the
   caller has one code path.
3. **`remove(workflow)`**: drop every route in `app.router.routes` whose
   `name` starts with `plugin:{workflow}:` and the `Mount` whose path is
   `/plugins/{workflow}/static`; drop the spec; `dispatch.set(workflow,
   None)`; `app.openapi_schema = None`. The builtin spec (`_builtin`)
   is refused — it is not a workflow. Returns the removed spec, `None`
   if there was none.
4. **`replace(spec)`**: remove then add, re-inserting at the removed
   entry's index so the manifest order is stable across a reload (22
   §Replace step 2).
5. **`HandlerDispatch`** becomes mutable: `self.specs` is a
   `dict[str, PluginSpec]` of the specs with handlers; `set(workflow,
   spec | None)` adds, swaps or drops one entry. `start()` subscribes
   once when the first handler-bearing spec is present, and a set that
   makes the map empty does **not** close the subscription — a later
   `add` reuses it. `_consume` reads the map per event, so a swap
   between two events is seen by the second. The subscription object is
   the same one for the life of the dispatcher (assert it).
6. **Readers read live.** `mount_manifest`'s route, `mount_actions`'s
   `_action(...)` lookup, `routers/workflows._plugin`, and `create_app`'s
   lifespan (which starts the dispatcher) take their specs from
   `request.app.state.plugins.specs` at request time. Grep for
   `app.state.plugins` and `state.plugins` and leave no reader holding
   a tuple from construction.
7. **`?v=`.** `registry._asset_urls` appends `?v=<sha256(file)[:12]>`
   to each URL. It already reads the directory per manifest request so
   that a rebuilt asset is listed without a restart; the hash rides the
   same read. `assetLoaded` in the SPA compares whole URLs, so nothing
   there breaks in this task — the *use* of the version is T087.
8. **`create_app(plugins=...)`** keeps its signature: a `Sequence
   [PluginSpec]` in, wrapped into `MountedPlugins`, and the loop in
   `create_app` that mounts assets moves into `MountedPlugins.add`.
   `Server.start` is unchanged in this task; it still passes
   `with_builtins(self._specs)`.
9. **Fold into 09 §Mounting**: the collection, that mounting follows
   registration on a running application, the route-name and mount-path
   removal rule, the OpenAPI cache drop, the subscription that survives
   a swap, the `?v=` on asset URLs — each a sentence or two pointing at
   22 §Live mounting.

## What this task is not

- No `Server` verb, no engine call, no event, no route under
  `/api/workflows`, no CLI. Nothing outside `athanore/plugins/`,
  `athanore/api/app.py`, `athanore/api/routers/workflows.py` and the
  one line in `api/static.py` if the mount needs a handle.
- No change to what a spec *is* (`collect`, `validate`, `PluginSpec`),
  to the actions endpoint's contract, or to the builtin panes.
- No SPA change; `web/` untouched.
- Snapshot untouched: the dump application registers no plugin, and
  the `?v=` is on data, not on the schema.

## Tests

`tests/plugins/`, on `create_app` with the store and engine fixtures
`tests/plugins/conftest.py` already builds, and the fixture workflow in
`fixture_wf.py` (add a second fixture workflow with a route, an asset
and an `on` handler, or parametrise the existing one):

- `test_mount_live.py` (new): after `create_app`, `add(spec)` → the
  route answers 200, `GET /api/plugins` lists the entry last with the
  asset URL carrying `?v=`, `GET` of that URL serves the file, the
  actions endpoint finds the action, `routers/workflows._plugin` sees
  the panels; publish an event the handler subscribes to → the handler
  ran; `remove(workflow)` → the route is 404 `{code: "not_found"}` (the
  API's 404, not Starlette's), the entry and the asset are gone, the
  action is 404, publish again → the handler did not run;
  `openapi.json` gains and loses the route's path across the two;
  `replace` keeps the manifest position; `_builtin` is first at every
  step and `remove("_builtin")` is refused.
- `test_mount.py`: `HandlerDispatch.set` swaps a handler between two
  events and the second reaches the new one; the `Subscription` object
  is identical before and after a swap and after the map is emptied
  and refilled; a handler that raises still drops and the next runs
  (existing test, re-run against the mutable map).
- `test_assets.py` / `test_registry.py`: the same directory read twice
  gives the same `?v=`; rewriting the file changes it; a directory with
  no `.js` is still `[]`.
- `tests/test_api_app.py`: `create_app(plugins=[...])` still accepts a
  list and a tuple.

## Verification

```sh
./scripts/test.sh -k "plugins or api_app"
./scripts/test.sh
git diff --exit-code tests/snapshots
```

## Done

- A workflow's plugin surface can be added to, replaced on and removed
  from a serving application with the manifest order, the 404s, the
  OpenAPI document and the handler subscription behaving as 22 §Live
  mounting says; asset URLs are versioned; 09 folded; gate green;
  snapshot unchanged.
