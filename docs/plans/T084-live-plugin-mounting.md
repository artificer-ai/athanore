# T084 — Live plugin mounting

**Task.** `docs/v1/17-serial-task-plan.md` § `### T084`.
**Specs.** `docs/v1/22-live-registration.md` §Live mounting (normative
for everything here), §Effects (Add step 2, Replace step 2, Remove step
3 — what T085 will call this for), §SPA (the `?v=` the notice depends
on), §Testing (the *Plugins* bullet); `docs/v1/09-plugins.md` §Mounting
(one router per workflow, the manifest's order, one subscription, "a
plugin cannot break the engine"), §Wire contract (an empty spec
contributes nothing), §Escape hatch (asset URLs); `docs/v1/08-api.md`
§Static (the SPA fallback is `router.default`, so routes added later
still match first), §Plugins; D29 (the bus never awaits a subscriber),
D139 (7)–(8) (the dispatcher and `create_app(plugins=)` as they are
today), D183 (the asset surface), D225 (no re-injection; the notice).

## What this task is

The plugin host's half of live registration: a workflow's routes,
assets mount, manifest entry and `on` handlers can be added to, replaced
on, and removed from an application that is already serving. It changes
how `create_app` *holds* the specs and how the routes that read them
find them. It adds no verb anyone outside the package calls yet —
T085's `Server.add/replace/remove` are the callers, and T085's plan
already names the surface it expects: `app.state.plugins.add(spec)`,
`.replace(spec)`, `.remove(name)`, called unconditionally with whatever
`collect(wf)` produced.

Three facts about the code decide the shape below:

- **Starlette matches `app.router.routes` on every request**, and the
  SPA is `app.router.default`, not a route (`api/static.py:318–330`).
  A router included after the application is built is therefore live
  on the next request, and a route removed from the list is gone on
  the next. There is nothing to rebuild.
- **The dispatcher today subscribes only if a spec has handlers**
  (`mount.py:HandlerDispatch.start`), and the lifespan only builds one
  if `any(spec.handlers …)` at startup (`api/app.py:lifespan`). Both
  conditions assume the set is fixed; a spec with handlers that arrives
  after boot would have no dispatcher to join.
- **`Server.register` drops an empty spec** (`server.py:214–217`) so the
  manifest has no entry for a workflow that declares nothing (09 §Wire
  contract). The collection must keep that fact true without the
  caller having to know it, because T085 calls `add(collect(wf))` for
  every workflow.

### `MountedPlugins` (`athanore/plugins/mount.py`)

1. **Construction.** `MountedPlugins(app, settings, bus=None,
   host=None)`. It mounts the two fixed routers itself — `mount_manifest
   (app)` then `mount_actions(app)`, in that order, for the reason the
   comment in `mount_plugins` gives — and builds `self.dispatch =
   HandlerDispatch(bus, (), host)` when `bus` is not `None`, else
   `self.dispatch = None` (an application without an engine has no bus
   and no events; the OpenAPI dump and the plugin tests without an
   engine are that application). `mount_plugins(app, specs)` is
   deleted; its only caller was `create_app`, and nothing in `tests/`
   or `examples/` imports it. Remove it from `__all__`; add
   `MountedPlugins`.
2. **State.** An ordered `list[PluginSpec]`, one per workflow name, in
   the order `add` was called — `create_app` adds `with_builtins(...)`
   in sequence, so `_builtin` is first on every served server; the
   manifest route keeps its `_builtins_first` partition anyway, so
   "builtins first" stays a property of the route (09 §Mounting).
   `specs -> tuple[PluginSpec, ...]` is a fresh tuple per call: a
   request that read it holds a snapshot and cannot see a list mutate
   under its loop. `get(workflow) -> PluginSpec | None`. No
   `__iter__`/`__len__`: every reader goes through `.specs`, so a grep
   for `.specs` finds every reader.
3. **`add(spec) -> None`.** Refuses (`ValueError`) a workflow already
   held — `Server.add` refuses a duplicate name before this is reached,
   so the check is a guard against a caller mistake, not a policy. An
   **empty spec** (`not spec`, the same truthiness `Server.register`
   tests) mounts nothing and records nothing, so the manifest stays as
   09 §Wire contract has it; the caller has one code path either way.
   Otherwise, in this order: `mount(app, spec)` (the existing function,
   unchanged — it names every route `plugin:{workflow}:{fn}` and
   `include_router`s it); `mount_plugin_assets(app, spec.workflow,
   directory, settings)` when `spec.assets_dir()` is not `None`; append
   to the list; `self.dispatch.set(spec.workflow, spec)` when there is
   a dispatcher; `app.openapi_schema = None`. The mount-assets loop in
   `create_app` moves here and is deleted there.
4. **`remove(workflow) -> PluginSpec | None`.** Refuses (`ValueError`)
   `BUILTIN_WORKFLOW`: the builtin entry is not a workflow and nothing
   in 22 removes it. Otherwise: filter `app.router.routes` in place,
   dropping every route whose `name` starts with `plugin:{workflow}:`
   (the colon is part of the prefix, so `plugin:a:` never matches
   `plugin:ab:…`) and every `Mount` whose `path` is
   `/plugins/{workflow}/static`; drop the spec from the list;
   `self.dispatch.set(workflow, None)`; `app.openapi_schema = None`.
   Returns the spec that was held, `None` if there was none — a
   workflow whose spec was empty was never held, and `remove` of it is
   a no-op, not an error. Removal mutates `app.router.routes` (the
   list Starlette iterates) rather than rebuilding the router, because
   the SPA fallback, the MCP route and the middleware stack hang off
   the router object.
5. **`replace(spec) -> None`.** `remove` then `add`, with the new spec
   inserted at the removed one's index (22 §Replace step 2: same
   position in the manifest). A name not currently held is appended —
   the registered workflow may have had an empty spec before and a
   real one now. A new spec that is empty removes the old and holds
   nothing. `replace(_builtin)` is refused through `remove`. One
   OpenAPI drop is enough but two are harmless; do not special-case.
6. **No lock.** Every mutation is synchronous and runs on the loop
   thread between awaits; a request in flight holds the spec its
   endpoint closed over and finishes on it, which is the same rule 22
   §Replace gives an attempt in flight. Say so in the class docstring.

### `HandlerDispatch` becomes mutable

7. **`self.specs` is a `dict[str, PluginSpec]`** of the handler-bearing
   specs by workflow name, in insertion order (delivery order stays
   registration order). The constructor still takes a `Sequence
   [PluginSpec]` and seeds the dict from those with handlers, so
   `dispatch_handlers(bus, specs, host)` and the two tests that call
   it (`test_mount.py:586, 665`) are unchanged.
8. **`set(workflow, spec | None)`.** `None`, or a spec with no
   handlers, pops the entry; a spec with handlers is set under its
   name — a swap keeps the entry's position (`dict` assignment to an
   existing key does), a new name goes last. It never touches the
   subscription or the task. `_deliver` iterates `self.specs.values()`
   — it already reads the collection per event, so the second of two
   events straddling a swap reaches the new handler.
9. **`start()` subscribes whenever it is called**, not only when a
   handler-bearing spec is present. The lifespan calls it once for any
   application that has an engine; `set` never does. The
   `Subscription` is the same object for the life of the dispatcher —
   `aclose()` is the only thing that closes it. The cost is one drained
   queue on a server whose plugins declare no `on` handler; the
   alternative — subscribing lazily on the first `set` that installs a
   handler — adds a "started but not subscribed" state and a second
   place that subscribes, for nothing 22 asks for. **Decision, record
   as the next D-row**: the plugin dispatcher subscribes at lifespan
   start regardless of whether anything currently subscribes, and
   `set` mutates the map under that one subscription.
10. Delete the `if self._task is not None or not self.specs` guard's
    second half; keep idempotence.

### `create_app` (`athanore/api/app.py`)

11. Signature unchanged: `plugins: Sequence[PluginSpec] | None`. After
    `install_openapi(app)` and before `mount_spa`, build
    `app.state.plugins = MountedPlugins(app, settings, bus=engine.bus if
    engine is not None else None, host=PluginHost.from_app(app) if
    engine is not None else None)` and `add` each spec in order. The
    `mount_plugins(...)` call and the assets loop go. The
    `app.state.plugins = tuple(...)` line goes: `app.state.plugins` is
    the collection from the moment it is set, and nothing sets it to a
    tuple first.
12. **Lifespan**: `plugins: MountedPlugins = app.state.plugins`; `if
    plugins.dispatch is not None: plugins.dispatch.start();
    stack.push_async_callback(plugins.dispatch.aclose)`. The
    `any(spec.handlers …)` predicate goes. `dispatch_handlers` stays as
    the convenience the tests use.
13. `PluginHost.from_app(app)` reads `app.state.store/engine/settings`
    at construction — all three are set before the collection is built,
    so building the host in `create_app` rather than in the lifespan
    changes nothing it sees.

### Readers read live

14. `mount_manifest`'s route and `mount_actions`'s `run_action` replace
    `getattr(request.app.state, "plugins", None) or ()` with
    `request.app.state.plugins.specs`. `routers/workflows._plugin` the
    same. `create_app` always sets the collection, and no test builds a
    bare `FastAPI()` and mounts the manifest on it (`tests/api/
    test_errors.py`, `tests/agents/conftest.py` and `tests/testing/
    test_fake_acp.py` build bare apps for other routers). Grep
    `state.plugins` and `state, "plugins"` under `athanore/` and leave
    no reader holding a tuple from construction; `_action(specs, wf,
    name)` keeps its `Sequence` parameter and is handed the snapshot.

### `?v=` on manifest asset URLs (`athanore/plugins/registry.py`)

15. `_asset_urls` appends `?v=<hashlib.sha256(path.read_bytes())
    .hexdigest()[:12]>` to each URL. It already reads the directory per
    manifest request (its docstring says why); the hash rides the same
    read. A file that `rglob` listed but `read_bytes` cannot open
    (`OSError`) is omitted from the list with a `warning` naming the
    path — a file that cannot be read cannot be served, and "unknown
    is omitted" is the rule (AGENTS §Real data only). The URL's path
    part is unchanged; `StaticFiles` ignores the query, so `GET` of the
    listed URL serves the file as before. The SPA's `assetLoaded`
    compares whole URLs and its `script.src` takes the URL verbatim,
    so nothing in `web/src` changes in this task; the *use* of the
    version is T087.
16. `manifest_entry`'s and `PluginSpec`'s docstrings mention the
    version where they describe the asset list. **Do not** change the
    `Field(description=…)` of `PluginManifestEntry.assets` or the
    docstring of the `manifest` route function or of `PanelOut` — all
    three are in `tests/snapshots/openapi.json` ("manifest changes only
    when the process does", "manifest changes only on restart"), and
    the task fixes the snapshot byte-identical. Their wording is stale
    after this task; T086, which regenerates the snapshot for the three
    routes, corrects it. Say so in a comment beside each.

### Fold into `docs/v1/09-plugins.md` §Mounting

17. Add a paragraph after "**One subscription** …" that says: mounting
    follows registration on a running application (22 §Live mounting);
    the application holds a live collection and every reader of it —
    the manifest, the actions endpoint, `GET /api/workflows/{name}` —
    reads its current specs per request; adding includes the router
    and appends the assets mount, removing drops every route named
    `plugin:{wf}:…` and the mount at `/plugins/{wf}/static`, replacing
    keeps the manifest position; every mutation drops the cached
    OpenAPI document; the dispatcher's one subscription outlives every
    swap so no event is missed across one. Each sentence points at 22
    §Live mounting. In §Escape hatch, where the URL form is given, add
    that the manifest's URLs carry `?v=<first 12 hex of the file's
    sha256>`, computed when the manifest is read, and point at 22 §SPA
    for what the SPA does with it. Nothing else in 09 changes.
18. `docs/v1/15-decisions.md`: the D-row of step 9. If the implementer
    makes any other choice the documents did not, a row for it too.
19. `docs/v1/17-serial-task-plan.md`: `**Status.** Done.` on `### T084`,
    in the same commit.

## What this task is not

- No `Server` verb, no engine call, no event, no route under
  `/api/workflows`, no CLI. `server.py` is untouched: `start()` still
  passes `with_builtins(self._specs)` and `register` still drops an
  empty spec — T085 rewrites both.
- No change to what a spec *is* (`collect`, `validate`, `PluginSpec`),
  to the actions endpoint's contract, to `mount()`, or to the builtin
  panes.
- No SPA change: `web/src` untouched. **One exception, tests only**:
  `web/e2e/plugin.spec.ts` selects the injected script by exact
  attribute, `script[data-athanore-asset="/plugins/plugged/static/
  playfield.js"]` (two places). With `?v=` on the URL that exact match
  fails and the gate is red. Change both to the prefix form
  `[data-athanore-asset^="/plugins/plugged/static/playfield.js"]` and
  nothing else in the file. This is the boring choice — the assertion
  means "the module the manifest listed was injected once", and the
  version is part of the URL now — and it is a test, not the SPA.
  Record it in the D-row of step 9 rather than a row of its own.
- Snapshot untouched: the dump application registers no plugin, and
  the `?v=` is on data, not on the schema. See step 16.

## Tests

`tests/plugins/`, on the fixtures `conftest.py` already builds.
`fixture_wf.fixture_workflow(name)` builds the reference workflow under
any name, with a route, an action, an `on("run.completed")` handler
that publishes `recorded(name)`, and `assets="./assets"` — so three
names of it give the order tests three distinct entries.

- **`conftest.py`**: a `live_app` fixture beside `app_with`, yielding
  `(app, client)` for `create_app(settings, engine, store,
  plugins=with_builtins(()))` with the lifespan run through
  `_lifespan` and the engine started (`await engine.start()`), torn
  down the same way. Tests that add a workflow also
  `engine.register(graph, Pool("test", settings.workers))` it so that
  a run of it can be submitted through the API and its `run.completed`
  reaches the handler.
- **`test_mount_live.py`** (new). On `live_app`, `plugins =
  app.state.plugins`:
  - *add*: `plugins.add(spec)` → `GET /api/plugins/{wf}/rules` is 200;
    `GET /api/plugins` lists `_builtin` first and `wf` last, its
    `assets` entry matching `^/plugins/{wf}/static/playfield.js\?v=
    [0-9a-f]{12}$`; `GET` of that exact URL is 200 with the module;
    `POST /api/plugins/{wf}/actions/override` is not 404;
    `GET /api/workflows/{wf}` carries the panels; `openapi.json` has
    `/api/plugins/{wf}/rules` under `paths`; submit a run through the
    API and complete it → the `recorded(wf)` event is on the bus.
  - *remove*: `plugins.remove(wf)` returns the spec → the route is 404
    with `{"code": "not_found"}` (the API's 404, from
    `api/static.py`'s handling of `/api/…`, not Starlette's
    `{"detail": …}`); the manifest has no entry; the asset URL is 404
    `not_found`; the action is 404; `openapi.json` no longer has the
    path; `dispatch.specs` has no `wf`; complete another run of the
    still-registered graph → no `recorded(wf)` event; `remove(wf)` a
    second time returns `None`.
  - *subscription identity*: `dispatch._subscription` (or a `running`/
    `subscription` accessor — add a read-only `subscription` property)
    is the same object before `add`, after `add`, after `remove`, and
    after a second `add`; `subscription.closed` is false throughout.
  - *replace*: add `alpha`, `beta`, `gamma`; `replace(collect(
    fixture_workflow("beta")))` → the manifest order is `_builtin,
    alpha, beta, gamma`; the new route answers; `replace` of a name
    never added appends; `replace` with an empty spec removes.
  - *empty spec*: `add(collect(Workflow-with-no-declarations))` mounts
    nothing, the manifest is unchanged, `get(name)` is `None`,
    `remove(name)` is `None`.
  - *refusals*: `remove("_builtin")` and `replace(builtin spec)` raise
    `ValueError`; `add` of a held name raises `ValueError`; `_builtin`
    is first after every step.
  - *no engine*: `create_app(settings, plugins=[…])` alone →
    `app.state.plugins.dispatch is None`, `add`/`remove` still mount
    and unmount routes.
- **`test_mount.py`**: `HandlerDispatch.set` — publish, swap the spec
  under the name, publish again: the first handler saw one event and
  the second saw the other; `set(name, None)` then `set(name, spec)`
  leaves the same `Subscription` object; a dispatcher started with no
  handler-bearing spec still holds an open subscription and delivers
  to a spec `set` later; the existing raising-handler and ordering
  tests re-run unchanged against the dict.
- **`test_registry.py`**: `test_manifest_lists_every_js_asset_as_a_url`
  asserts each URL is `path?v=<12 hex>` with the paths in the same
  sorted order; a manifest built twice from the same directory gives
  the same list; rewriting `a.js` changes only `a.js`'s `?v=`; a
  directory with no `.js` is still `[]`; an unreadable file is omitted
  (chmod 000, skipped when running as root).
- **`test_assets.py`** lines 280 and 427 and **`test_suite.py`** line
  344 (`entry["assets"] == [ASSET_URL]`): the assertions become
  path-plus-version checks; `test_suite.py:854`'s `GET ASSET_URL`
  keeps working because the path is unchanged, and a second `GET` of
  the listed URL (with the query) is added.
- **`tests/test_api_app.py`**: `create_app()` puts a `MountedPlugins`
  on `app.state.plugins` with `specs == ()` and `dispatch is None`;
  `create_app(plugins=[spec])` and `create_app(plugins=(spec,))` both
  hold one spec.
- **`web/e2e/plugin.spec.ts`**: the two selectors, per "What this task
  is not".

## Verification

```sh
./scripts/test.sh -k "plugins or api_app"
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
```

## Done

- A workflow's plugin surface can be added to, replaced on and removed
  from a serving application with the manifest order, the 404s, the
  OpenAPI document and the handler subscription behaving as 22 §Live
  mounting says; asset URLs are versioned; 09 §Mounting and §Escape
  hatch folded; the D-row written; `**Status.** Done.` on T084; gate
  green including Playwright; snapshot byte-identical.
