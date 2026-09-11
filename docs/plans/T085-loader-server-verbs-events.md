# T085 — Loader, server verbs, events

**Task.** `docs/v1/17-serial-task-plan.md` § `### T085`.
**Specs.** `docs/v1/22-live-registration.md` §Terms, §Server surface,
§Effects (the whole sequence each verb performs), §Pools, §Reloading a
module, §Persistence, §Wire (the `stage` list only — no route here),
§Events; `docs/v1/02-architecture.md` §`athanore.toml` layout, §Library
choices, §Layering; `docs/v1/04-engine.md` §Live registration,
§Programmatic host; `docs/v1/09-plugins.md` §Discovery, §Registration
and validation; `docs/v1/11-cli.md` §Server, §Exit codes;
`docs/v1/18-event-payloads.md` §Envelope, §Typing; `docs/v1/13-testing.md`
§Pyramid; D220 (persists as a toml row only), D223 (the toml is not
consulted by a live registration), D224 (subtree purge), D226
(`register` after `start()` raises), D228 (`tomlkit`), D229–D235 (what
T083 built and how it fails), D237 (an empty spec is held nowhere).

This plan was refined against the code after T083 and T084 landed:
`Engine.replace` is a coroutine taking `str | Pool | None` and only ever
reads a pool's *name* (D231, D233); `Engine.unregister(name) ->
list[int]` and `recover(engine, [name])` exist with the failure types
D232/D234 give; `MountedPlugins` on `app.state.plugins` has `add`,
`replace`, `remove` and holds an empty spec nowhere (D237). Everything
below calls those and adds nothing to them.

## What this task is

The composition root learns the three live verbs and sequences what
T083 and T084 provide; the loader moves to where the API can reach it
and learns to load a target a second time; `athanore.toml` learns
`target`, read at boot and written on request; the three events exist
end to end. After this task a programmatic host can `await
server.add(wf, target=..., persist=True)` on a serving process and
everything follows — engine, plugins, recovery, event, the toml row —
and `athanore serve` picks the row up on the next boot. There is still
no route: that is T086.

### The loader (`athanore/plugins/discovery.py`)

1. **Move** `load_target`, `_load_module`, `_load_file` and
   `_prepend_sys_path` from `athanore/cli/serve.py` to
   `athanore/plugins/discovery.py`. `discovery` sits in no
   import-linter tier and imports only `athanore.workflow`, so `api`
   (T086) and `cli` can both reach it; it must stay that way — nothing
   from `engine`, `server`, `cli` or `api` is imported here. `cli.serve`
   keeps a thin `load_target(target)` wrapper that calls the moved one
   and maps `LoadError` to `typer.BadParameter(str(exc))` (exit 2, 11
   §Exit codes), so `tests/cli/test_serve.py`'s imports and its exit-2
   parametrisation stand as they are.
2. **`LoadError`** in `discovery`:

   ```python
   class LoadError(Exception):
       def __init__(self, message: str, *, stage: LoadStage, target: str,
                    detail: str, conflict: bool = False) -> None
   ```

   `LoadStage = Literal["target", "import", "attribute", "finalize",
   "plugins", "register"]` (22 §Wire). `str(exc)` is `message` — the
   one-line sentence the loader already produces today (`"… is not a
   workflow target; name one as …"`, `"{where} has no attribute
   {attr!r} ({target})."`, `"{target} could not be imported: {exc}"`,
   `"{target} is a {type}, not a Workflow."`, `"{target} names {path},
   which is not a file."`). `detail` is the underlying exception's
   full text, untouched; for `target` — where there is no underlying
   error — it equals `message`. `conflict` is `False` from the loader
   and set only by `Server.add` on a duplicate name (T086 maps
   `stage == "register" and conflict` to 409 without parsing text).
   The loader raises `target`, `import` and `attribute`; `finalize`,
   `plugins` and `register` are raised by the server's verbs (step 9),
   so the API can report where a registration stopped with one
   exception type. `DiscoveryError` stays for the entry-point path.
3. **A factory is a target.** `load_target` accepts an attribute that
   is a `Workflow` or a callable returning one, exactly as `_workflow`
   does for an entry point (22 §Reloading a module). Pull the shared
   check into `_resolve(value, describe: str) -> Workflow`, raising a
   private `_NotAWorkflow(detail)` that each caller wraps in its own
   type: `discover()` in `DiscoveryError` with the entry-point sentence
   it already builds, `load_target` in `LoadError(stage="attribute")`.
   A factory that raises is `attribute` too — the attribute did not
   yield a workflow — with the exception's text as `detail`
   (**decision**: 22 gives `import` to "the module or file would not
   load" and `attribute` to "no such attribute, or not a `Workflow`";
   a factory that raised is the second kind of failure).
4. **`load_target(target, *, reload=False) -> Workflow`.** The first
   load is byte-for-byte what `cli.serve` does today. With `reload`:
   - a **module target** (`where` has no `.py` suffix and no path
     separator) first collects `__file__` of every `sys.modules` entry
     whose key is `where` or starts with `where + "."`, deletes those
     entries, calls `importlib.invalidate_caches()` (a submodule
     written since the first import is otherwise invisible to the
     finder's directory cache), then imports as on a first load;
   - a **file target** executes afresh as `_load_file` already does —
     `sys.modules[stem]` is replaced by the new module object;
   - either way `linecache.checkcache(path)` is called for every file
     collected above and for the (re)loaded module's `__file__`, so
     `inspect.getsource` reads the new text. (`checkcache` compares
     size and mtime; the test's edited text differs in length so the
     check is exact regardless of the file system's timestamp
     granularity.)

   A failed load leaves `sys.modules` as the failure found it (22
   §Reloading a module): `_load_file` pops its half-built entry as
   today; a module target's purge is not undone. `_load_module` catches
   `Exception` (not `BaseException`) around the import/exec and raises
   `LoadError(stage="import")` — a `SyntaxError` in the file and an
   `ImportError` from user code are both `import`.
5. **`discover()` returns `list[Discovered]`**, `Discovered` a frozen
   dataclass `(workflow: Workflow, target: str)` with `target` the entry
   point's `value` (`module:attr`) — the target a reload of a
   discovered workflow re-resolves (22 §Terms). Update the handful of
   assertions in `tests/cli/test_discovery.py` that index the list;
   `cli.serve.discovered()` passes the pairs through.
6. **Result types beside `LoadError`**, both frozen dataclasses, both
   in `discovery` so T086's API tier can name them without importing
   the composition root:
   `Registered(name: str, persisted: Path | None)` and
   `RemovedWorkflow(workflow: str, task_ids: tuple[int, ...],
   persisted: Path | None)`. Not exported from `athanore/__init__.py`
   (02 §Public API's list is unchanged by 22).
7. **The toml tables move too.** `layout`, `_pools`, `_bindings` and
   `WORKFLOW_KEYS` leave `cli.serve` for `discovery` as
   `read_layout(toml_path: Path) -> Layout`, `Layout` a frozen dataclass
   `(pools: dict[str, int], bindings: dict[str, str], targets: dict[str,
   str])` — `bindings` is name → pool for every row that names one (as
   today), `targets` is name → target for every row that has one.
   `WORKFLOW_KEYS = frozenset({"pool", "target"})`; `target` must be a
   `str` of the `where:attr` shape or the row is refused, and an unknown
   key inside a row stays an error naming the two keys it takes (02).
   Every refusal is `LayoutError(path, detail)` (a new exception in
   `discovery`, `str()` the sentence the CLI prints today). A missing
   file is `Layout({}, {}, {})`. `cli.serve.layout(root_path)` stays,
   as a wrapper returning `(layout.pools, layout.bindings)` and mapping
   `LayoutError` → `typer.BadParameter`, so the existing serve tests
   and `_pool_for` are untouched; boot (step 12) and the host (step 13)
   read the table through the one function.

### The server (`athanore/server.py`)

8. **Targets.** `Server.register(wf, pool=None, *, target=None)`
   records `target` in `self._targets: dict[str, str | None]`, kept in
   step with `_workflows`; `server.targets -> dict[str, str | None]` is
   a copy in registration order (a `dict` satisfies 22's `Mapping`).
   `register` after `start()` raises `RuntimeError("the server is
   serving; use add()")` (D226) — `self._serve_task is not None` is the
   predicate `start()` already uses. `register` is otherwise unchanged:
   sync, chains, `GraphError` for the three name refusals.
9. **One validation, six stages.** Split what `register` does today into
   three private steps — `_finalize(wf) -> Graph` (`wf.finalize()`),
   `_check_name(name)` (verb, duplicate, pool-name: the three
   `GraphError`s as today), `_check_plugins(wf, graph) -> PluginSpec`
   (`collect` + `validate`) — and have `register` call them as it does
   now, letting their exceptions through. `add` and `replace` call the
   same three and wrap: `GraphError` from `_finalize` →
   `LoadError(stage="finalize")`; `PluginValidationError` (and any
   `PluginError`) from `_check_plugins` → `stage="plugins"`; the name
   refusals → `stage="register"`, with `conflict=True` for `add`'s
   duplicate. `message` is the refusal's own sentence, `detail` the
   same text, `target` the target given or `""` for a programmatic
   object. `replace` on a name that is not registered is
   `LoadError(stage="register")` (T086's `PUT` 404s before reaching
   it; a host calling directly gets the same exception type as every
   other refusal).
10. **Pools.** `add` and `replace` take `pool: str | Pool | None`,
    resolved by one private `_resolve_pool(pool) -> Pool | None`:
    `None` → `None`; a `str` → `self.engine.pools.get(name).pool`,
    whose `KeyError` (D234's type for "no such pool"; the sentence is
    the registry's) propagates unchanged — T086 maps it to `422
    unknown_pool`; a `Pool` object **before `start()`** is passed
    through as `register` passes it (the boot-time idiom: a host
    declares capacity by registering with a `Pool`), and **while
    serving** contributes only its name and must exist (`KeyError`
    otherwise) — the rule D233 gives `Engine.replace`, applied to `add`
    so a live registration never creates or resizes a pool (22 §Pools).
    **Decision** to record. `replace(pool=None)` keeps the binding
    (`engine.replace` does that itself).
11. **The three verbs.** Each runs its refusals first — steps 9 and 10
    and, with `persist=True`, the write of step 16 — and only then
    mutates, in exactly 22 §Effects' order. "Serving" below is
    `self._serve_task is not None and self.app is not None`.

    **`await add(wf, pool=None, *, target=None, persist=False) ->
    Registered`:** validate; persist; `self.engine.register(graph,
    pool)`; `_workflows[name] = wf`, `_targets[name] = target`, and the
    spec appended to `_specs` when it is non-empty (as `register` does;
    `_specs` is what `start()` hands `create_app`, so it must be kept
    true before *and* after start). If serving:
    `self.app.state.plugins.add(spec)` — should the mount raise (a
    route FastAPI cannot build; `MountedPlugins._insert` has already
    undone its own half), `await self.engine.unregister(name)` and drop
    the three records before re-raising, so a failed add leaves the
    server as it was; then `await recover(self.engine, [name])` (T083 —
    it emits `engine.recovered` itself when it reset anything); then
    `workflow.registered` in its own `store.uow()`; then
    `self.engine.notify()`. Before `start()` only the engine and the
    three records change — what `register` does — and nothing is
    emitted.

    **`await replace(wf, pool=None, *, target=None, persist=False) ->
    Registered`:** the name must be registered; validate; persist;
    `await self.engine.replace(graph, pool_name_or_None)` — its
    `ValueError` (pool move with attempts in flight) and `KeyError`
    (unknown pool) propagate as they are; `_workflows[name] = wf`;
    `_targets[name] = target if target is not None else
    _targets[name]` (**decision**: `replace(target=None)` keeps the
    recorded target — T086's "reload what you loaded" passes the
    recorded one explicitly, and a host replacing with an object it
    built should not lose the record); the spec replaces the old one
    at its index in `_specs`, is appended when the old was empty, and
    is dropped when the new is empty. If serving:
    `self.app.state.plugins.replace(spec)` (D237 makes the empty case
    a removal); `workflow.replaced`; `notify()`. No recovery (22
    §Replace step 3).

    **`await remove(name, *, persist=False) -> RemovedWorkflow`:**
    registered or `LoadError(stage="register")`; persist (the row is
    removed); `task_ids = await self.engine.unregister(name)`; the
    three records drop the name; if serving:
    `self.app.state.plugins.remove(name)` (`None` for a workflow that
    declared nothing is fine) and `workflow.unregistered {workflow,
    task_ids}`. No `notify()` — nothing became ready. Returns
    `RemovedWorkflow(name, tuple(task_ids), persisted)`.
12. **Emitting.** The three events are written through
    `async with self.store.uow() as uow: uow.emit(Event(run_id=None,
    task_id=None, name=..., data=payload.model_dump(), created=now()))`
    — the shape `Engine._announce_stopping` uses — only when serving.
    `pool` in the payload is `self.engine.pools.for_workflow(name).name`
    read after the engine step; `target` is the recorded target and is
    absent on the wire when `None` (the `EventModel` serializer already
    drops an omittable `None`).

### Boot and persistence

13. **`Server.register_configured() -> ConfiguredRows`**, sync, before
    `start()` (the same `RuntimeError` as `register` after it). Reads
    `read_layout(self.settings.root_path / "athanore.toml")` — the path
    the settings source resolves — and for each row with a `target`, in
    the file's order: `load_target(target)`; the workflow's name must
    equal the row's key, else `LoadError(stage="register", target=...,
    detail=...)` naming the key, the name and the target; a name already
    registered is **skipped**, recorded as `Skipped(name, target,
    registered_target)` and logged at WARNING — 22 §Persistence's "a
    positional that loads the same name wins and the row is skipped
    with a warning naming both targets", and for a host, a `register`
    it already made wins the same way; otherwise `self.register(wf,
    pool, target=target)` with `pool = Pool(bound, layout.pools[bound])`
    when the row names one — a pool `[pools]` does not declare is a
    `LayoutError` with the sentence `serve` prints today (`workflow
    `x` is bound to pool `y`, which `[pools]` in … does not declare`) —
    and `None` otherwise. `ConfiguredRows` is a frozen dataclass
    `(registered: tuple[str, ...], skipped: tuple[Skipped, ...])`, so
    `serve` can print each skip in the CLI's own voice and a host can
    read what happened. A file with no such rows registers nothing; a
    missing file is not an error. Rows without a target are bindings
    only and are not touched here (they are `serve`'s and `_pool_for`'s
    as today).
14. **Boot order in `serve`** (11 §Server; 22 §Persistence): the
    `Server` is built first, then (1) each positional is loaded and
    registered with its `_pool_for` pool and `target=<the positional as
    given>`; (2) `server.register_configured()`, every `Skipped`
    printed with `warn(...)` naming both targets, and `LoadError` /
    `LayoutError` / `GraphError` / `ValueError` / `KeyError` printed
    with `fail(str(exc))` and exit 2 (`EXIT_USAGE` — a row is a
    positional written down and costs what a positional costs); (3)
    unless `--no-discover`, every `Discovered` whose name is not in
    `server.workflows` — the positionals *and* the rows — is registered
    with `target=discovered.target`; the ones dropped are the shadowed
    ones 09 §Discovery describes. The "binding names a workflow this
    server does not run" warning stays, computed after step (3).
    `DiscoveryError` keeps its exit 1.
15. **`athanore/plugins/persist.py`** — the one module in `athanore/`
    that imports `tomlkit` (D228; add `tomlkit>=0.13` to
    `pyproject.toml`'s dependencies, `uv lock`, and a row in 02
    §Library choices). Two functions and one exception:

    ```python
    def write_row(path: Path, name: str, target: str, pool: str | None) -> None
    def remove_row(path: Path, name: str) -> None
    class PersistError(Exception): path: Path; detail: str
    ```

    `write_row` parses the file when it exists (`tomlkit.parse`), else
    starts from an empty document; ensures a `[workflows]` table
    (`doc.setdefault("workflows", tomlkit.table())`); sets
    `doc["workflows"][name]` to an inline table `{target = "…"}` plus
    `pool = "…"` only when given — an existing row under the name is
    replaced whole, so a `pool` the request did not name is dropped
    from it (the row is the registration the caller asked for, and a
    default-pool workflow stays on the default pool if `workers`
    changes — 22 §Persistence); writes the document back with
    `tomlkit.dumps`. Every other byte — comments, key order, the other
    rows' formatting, the `[pools]` table — survives, which is the
    whole reason for `tomlkit`. `remove_row` deletes the key and is a
    no-op (no write) when the file or the row is absent; an emptied
    `[workflows]` table is left in place. Both raise
    `PersistError(path, detail)` on an unreadable, unparsable
    (`tomlkit.exceptions.ParseError`) or unwritable file. The write is
    a plain `path.write_text` — an in-place edit of the operator's
    file, not a rename over it, so its mode and ownership are kept.
16. **`persist=True`** on `add`, `replace`, `remove`. `add`/`replace`
    require a `target` — `ValueError("persist=True needs a target; a
    Workflow object cannot be written to athanore.toml")` otherwise —
    and call `write_row(path, name, target, pool_name)` with
    `pool_name` the *name the caller gave* (`None` when none: D223's
    "`pool` present only when the request named one"), **after** every
    validation of steps 9–10 and **before** the engine step; `remove`
    calls `remove_row` before `engine.unregister`. A `PersistError`
    therefore leaves the server untouched, which is why the order is
    fixed. The path is `self.settings.root_path / "athanore.toml"`, and
    it is what `persisted` carries in the result; `persisted` is `None`
    without `persist`.
17. **Never the source.** No code path here opens a `.py` for writing;
    the server test's fixture hashes every `.py` under `tmp_path`
    before and after and asserts them equal, so it stays that way.

### The events

18. `EventName.workflow_registered = "workflow.registered"`,
    `workflow_replaced`, `workflow_unregistered` under a `# Workflows`
    comment **after** the `# Engine` block in `athanore/events/names.py`
    (the block comment is what the site's generated events page groups
    by; the position is what `tests/test_events_names.py` checks against
    03's table order). Payloads in `athanore/events/payloads.py` under a
    `# Payloads — workflows` banner after the engine ones:
    `WorkflowRegistered {workflow: str, pool: str, target: str | None =
    None}`, `WorkflowReplaced` (same three fields, its own class),
    `WorkflowUnregistered {workflow: str, task_ids: list[int]}`, each
    docstring ending "No ``run_id``."; the three `…Event(EventFrame)`
    envelopes after `EngineStoppingEvent`; the three `Annotated[...,
    Tag(...)]` entries in `EventEnvelope` after `EngineStoppingEvent`'s.
    `EventFrame`'s docstring: "``run_id`` is absent on ``engine.*`` and
    ``workflow.*``". `ENVELOPES`/`PAYLOADS` derive themselves.
19. **The SPA's runtime list.** `web/src/realtime/sse.ts`'s
    `EVENT_NAME_TABLE: Record<EventName, true>` is what makes the
    generated `EventName` type a value the feed subscribes with; the
    three new names fail `pnpm -C web typecheck` as missing keys until
    they are added. Add the three lines after `'engine.stopping': true`.
    That is the one file under `web/src` outside `api/gen` this task
    touches, and it is the contract's mirror rather than UI (T087 is
    the UI).
20. **Regenerate**, in this order, and commit every result:
    `uv run scripts/dump_openapi.py && pnpm -C web gen` (the envelope
    union is in `tests/snapshots/openapi.json` and
    `web/src/api/gen/types.gen.ts` through `GET
    /api/runs/{id}/events`), then `uv run scripts/gen_docs.py` (the
    site's `reference/events.md` gains a "Workflows" group, and the
    `athanore.toml` example on `reference/settings.md` gains its
    `target` row — edit the example in `scripts/gen_docs.py`, not the
    page) and `uv run scripts/gen_skills.py` (the skills' copies of
    `events.md` and `settings.md`). `git diff --exit-code
    tests/snapshots web/src/api/gen docs/site/src/reference skills`
    must be clean afterwards.
21. **Stale wording that this regeneration exposes.** `plugins/mount.py`
    carries a comment (above `PanelOut`) saying T086 will correct the
    "changes only on restart" sentences in `PanelOut`'s docstring, the
    `assets` description of `PluginManifestEntry` and the manifest
    route's docstring, because T084 left the snapshot untouched. T085
    is the first task to regenerate the snapshot, so it corrects them
    here (the manifest changes on every live registration — 22 §Live
    mounting) and deletes the comment; `routers/system.py`'s
    `started_at` sentence ("A change means a restart") is still true
    and stays.

### The folds

22. 03 §Event vocabulary: three rows between `engine.stopping` and the
    `plugin.<wf>.<name>` row — `workflow.registered` | workflow, pool,
    target | live registration (22) — and its two siblings. 18: the
    §Envelope sentence and a `### Workflows` table after §Engine with
    the three payloads. 04 §Programmatic host: one paragraph under the
    snippet — the three coroutines, `targets`, `register_configured()`,
    and that they are what 22 §Server surface specifies. 11 §Server:
    `load_target`'s new home and the factory form; that `serve`
    records each positional as its target and each discovered
    workflow as its entry point's value; the boot order as three
    numbered stages with the rows in the middle, the key-must-match
    rule, and the two shadowing rules (positional over row with a
    warning; row over discovered). 09 §Discovery: `discover()` yields
    `(workflow, target)` pairs; a row with a `target` shadows a
    discovered workflow of the same name exactly as an explicit target
    does; the toml example gains `hello = { target =
    "workflows/hello.py:wf" }`. 02 §`athanore.toml` layout: the
    `target` key in the example and the sentence that a row with one is
    a registration, read at boot and written on request; §Library
    choices: a `tomlkit` row (editing `athanore.toml` in place;
    `tomllib` stays the reader). 15: new rows for the decisions this
    plan marks (**decision**): the factory-raised stage, `add`'s pool
    semantics before and after `start()`, `replace(target=None)`
    keeping the record, `discover()` returning pairs, the toml reader
    living in `plugins.discovery`, and T085 correcting the manifest
    wording T084 left for T086. The site: `guide/workflows.md`
    §Registering and serving gains a short paragraph on `add` /
    `replace` / `remove` after `start()` and `register_configured()`;
    `guide/deployment.md`'s `[workflows]` example gains a `target` row
    with one sentence; nothing about CLI verbs or routes (T086).

### As built (refinements the code made to the steps above)

- Step 11/22, the order in the events table on `add`: `engine.recovered`
  (when anything was reset) precedes `workflow.registered`, because 22
  §Add numbers recovery step 3 and the event step 4 and the verb runs
  the steps in that order; the test in `tests/test_server.py` asserts
  that sequence (D247). 17 § T085's "emits `workflow.registered` then
  `engine.recovered`" is read as a list.
- Step 11, `replace`: a pool move is pre-checked against
  `engine.attempts_of(name)` *before* the row is written, so a
  `persist=True` replace refused for its move has written nothing;
  `Engine.replace` stays the authoritative check between ticks (D245).
- Step 15, `remove_row` returns whether a row was removed, and
  `RemovedWorkflow.persisted` is `None` when there was none to remove
  (D244) — 22 §Server surface's "`None` when no file was touched".
- Step 13, `ConfiguredRows` and `Skipped` live in `athanore/server.py`
  (they are the composition root's result types; only `serve` and a
  host read them). `Server.toml_path` is the one spelling of
  `root_path / "athanore.toml"`.
- Step 4, `_load_file` wraps what `exec_module` raises (a `SyntaxError`,
  an `ImportError` from the file's own code, any `Exception`) in
  `LoadError(stage="import")` after popping the half-built entry, as
  `_load_module` does for a module target.
- Step 14, `serve`'s discovery loop filters against the names registered
  by the positionals and the rows only — two distributions advertising
  one name still collide at `register` (exit 1), as before.

## What this task is not

- No route, no registrar port, no `WorkflowOut.target`, no `ErrorCode`,
  no CLI verb: T086. `athanore workflows reload` does not exist yet,
  and nothing in this task reads HTTP.
- No SPA change beyond the regenerated client and the three keys of
  step 19.
- No engine or plugin-host behaviour beyond calling what T083 and T084
  built; if a call turns out to need something they did not provide,
  that is a gap in those tasks to fix on this branch and note in their
  plan files, not a reason to reach around them.
- No persistence anywhere but the toml row (D220): no database table,
  no `.athanore/` file. No file watcher (D222). No write to any `.py`.
- No reload of anything outside the target's own subtree; no
  hot-swapping of an attempt in flight.
- No change to `Workflow.run()`, to `Engine`, to `MountedPlugins`.

## Tests

Unique basenames (the suite has no `__init__.py` files, so two
`test_discovery.py` would collide).

- `tests/plugins/test_load_target.py` (new; the loader): a file target
  under `tmp_path` loads; rewritten with different text and loaded
  with `reload=True`, the returned workflow is a new object with the
  new node set, `sys.modules[stem]` is the new module, and
  `inspect.getsource` of the new body shows the new text; a module
  target under a `tmp_path` package on `sys.path` with a submodule and
  a sibling module — after editing the submodule and reloading, both
  the package's and the submodule's module objects are new and carry
  the change, and the sibling's is `is` the old one; a helper
  imported from outside the package is unchanged; a factory attribute
  loads; each of `target`, `import` (a file with a `SyntaxError`, an
  `ImportError` raised by the file's own code, a missing module),
  `attribute` (missing, not a `Workflow`, a factory that raises)
  raises `LoadError` with that `stage`, `target` set, `detail` the
  original text and `conflict` false; a failing reload of a file
  target leaves `sys.modules` without the stem and a failing reload of
  a module target leaves the purge in place; `read_layout` reads
  `pools`, `bindings` and `targets`, refuses an unknown key naming both
  known ones, a non-string `target`, a malformed one, and a non-table
  row, each as `LayoutError`; `discover()` pairs each workflow with its
  entry point's value (`tests/cli/test_discovery.py`'s `install`
  fixture, whose existing assertions are updated to `.workflow`).
- `tests/cli/test_serve.py` (extended): `serve` records targets — a
  positional as typed, a row's target, a discovered value — visible on
  `served[0].targets`; exit 2 and the same messages for a bad
  positional (existing parametrisation, now through the wrapper); a
  row with `target` and `pool` loads and is bound to that pool; a row
  whose key is not the workflow's name is exit 2 naming key, name and
  target; a positional and a row of one name → the positional's target
  is recorded and one warning names both; a row and a discovered
  workflow of one name → the row's target; a row naming an undeclared
  pool is exit 2 with the existing sentence.
- `tests/plugins/test_persist.py` (new): on a `tmp_path` toml with a
  header comment, a `[pools]` table, an inline comment on a row and
  two existing rows — `write_row` adds a third and the file differs
  from the original by exactly that line; `write_row` on an existing
  name replaces its inline table only, dropping a `pool` the call did
  not give; `pool` absent when not given; a missing file is created
  holding just `[workflows]` and the row; a file with no `[workflows]`
  table gains one after its existing content; `remove_row` deletes
  only the row, leaves an emptied table, and is a no-op that does not
  rewrite an absent row or an absent file (mtime unchanged); an
  unparsable file and a read-only file raise `PersistError` carrying
  the path.
- `tests/test_server.py` (extended), on a started `Server` with parked
  bodies of the `tests/engine/test_unregister.py` kind (or
  `MockAgent`, where a body wants an agent):
  `add` mounts (the plugin route answers, the manifest lists it last),
  resets a row left `in_progress` under that name by a prior `remove`,
  and the events table then reads `workflow.registered` before
  `engine.recovered`, both with `run_id` `None`, and a run submitted
  afterwards dispatches; `replace` emits `workflow.replaced` with the
  bound pool and the recorded target, the running attempt completes on
  the old body, and the next task of the run dispatches on the new
  graph; `replace` with a different pool name and an attempt in flight
  raises `ValueError` and changes nothing; `replace(target=None)` keeps
  the recorded target; `remove` returns the interrupted ids, emits
  `workflow.unregistered` naming them, the plugin route is 404, the
  manifest entry is gone, and `GET /api/runs/{id}` reads
  `unregistered: true`; `register` and `register_configured` after
  `start()` raise `RuntimeError` naming `add`; before `start()` the
  three coroutines change `workflows`/`targets` and the engine and the
  events table stays empty; each `LoadError` stage the verbs raise
  (`finalize`, `plugins`, `register` for a verb name, a pool name, a
  duplicate — with `conflict` true — and `replace` of an unregistered
  name) leaves `workflows`, `targets` and the engine untouched;
  `add(pool="nope")` raises `KeyError` naming the known pools;
  `add(wf, Pool("fresh", 1))` before `start()` creates the pool and
  after `start()` raises `KeyError`; `targets` is in registration
  order with `None` for a programmatic registration;
  `add(persist=True)` without a target raises `ValueError`;
  `add(..., persist=True)` writes the row, returns `persisted` as the
  path, and the workflow is registered; a failing validation writes
  nothing; a `PersistError` (read-only file) registers nothing and
  emits nothing; `remove(persist=True)` removes the row and only the
  row, and `persisted` is the path; `remove(persist=True)` of a name
  with no row is not an error; `register_configured()` on a toml with
  two target rows registers both with targets and pools recorded,
  skips a name the host registered first (reported in `skipped`, one
  WARNING), refuses a key that is not the workflow's name and a pool
  `[pools]` does not declare; an autouse fixture hashes every `.py`
  under `tmp_path` before and after and asserts equality across the
  whole module.
- `tests/test_events_names.py` (extended): the existing contract tests
  pick up the three names; add the "no `run_id`" assertion for
  `workflow.*` beside the one for `engine.*`, and a serialisation check
  that `WorkflowRegistered(target=None)` omits `target`.
- `tests/test_openapi_snapshot.py`, `tests/test_docs_site.py`,
  `tests/test_skills.py`: regenerated artefacts match. `pnpm -C web
  typecheck && pnpm -C web test`: the `sse.test.ts` loop over
  `EVENT_NAMES` covers the three new keys.

## Verification

```sh
./scripts/test.sh -k "load_target or discovery or serve or server or persist or events or snapshot or docs_site or skills"
uv run scripts/dump_openapi.py && pnpm -C web gen
uv run scripts/gen_docs.py && uv run scripts/gen_skills.py
git diff --exit-code tests/snapshots web/src/api/gen docs/site/src/reference skills   # after committing the regen
uv run lint-imports                                  # discovery/persist import nothing above their station
./scripts/test.sh
```

## Done

- `Server.add/replace/remove/targets` work on a serving process with
  22 §Effects' sequence and events, and persist to and from
  `athanore.toml` on request; `athanore serve` and
  `register_configured()` load `target` rows with the stated
  precedence; `load_target` lives in `plugins.discovery`, reloads a
  module subtree and a file, and names its stage; the three events
  exist end to end through the snapshot, the generated client, the
  SPA's runtime list and the generated reference; folds and decision
  rows landed; `**Status.** Done.` on T085 in 17; gate green.
