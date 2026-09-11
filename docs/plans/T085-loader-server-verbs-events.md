# T085 — Loader, server verbs, events

**Task.** `docs/v1/17-serial-task-plan.md` § `### T085`.
**Specs.** `docs/v1/22-live-registration.md` §Terms, §Server surface,
§Effects (the whole sequence each verb performs), §Reloading a module,
§Persistence, §Events; `docs/v1/02-architecture.md` §`athanore.toml`
layout; `docs/v1/04-engine.md` §Programmatic host; `docs/v1/09-plugins.md`
§Discovery, §Registration and validation; `docs/v1/11-cli.md` §Server;
`docs/v1/18-event-payloads.md` §Envelope, §Typing; D220 (not
persists as a toml row), D224 (subtree purge), D226 (`register` after
start raises), D228 (`tomlkit`).

## What this task is

The composition root learns the three live verbs and sequences what
T083 and T084 provide; the loader moves to where the API can reach it
and learns to load a target a second time; `athanore.toml` learns
`target`, read at boot and written on request; the three events exist.
After this task a programmatic host can `await server.add(...,
persist=True)` on a serving process and everything follows — engine,
plugins, recovery, event, the toml row — and `athanore serve` picks the
row up on the next boot. There is still no route: that is T086.

### The loader

1. **Move** `load_target`, `_load_module`, `_load_file`,
   `_prepend_sys_path` from `athanore/cli/serve.py` to
   `athanore/plugins/discovery.py`. `discovery` sits in no import-linter
   tier and imports only `athanore.workflow`, so `api` (T086) and `cli`
   can both reach it. `cli.serve` keeps a thin `load_target` wrapper that
   maps `LoadError` to `typer.BadParameter` (exit 2, 11 §Exit codes)
   with the same messages the serve tests assert today.
2. **`LoadError(stage, target, detail)`** in `discovery`, `stage` one
   of `target | import | attribute | finalize | plugins | register` (22
   §Wire). The loader raises the first three; `finalize`, `plugins` and
   `register` are raised by the server's verbs (below) so the API can
   report where a registration stopped with one exception type.
   `DiscoveryError` stays for the entry-point path.
3. **A factory is a target.** `load_target` accepts an attribute that
   is a `Workflow` or a callable returning one, exactly as `_workflow`
   does for an entry point (22 §Reloading a module); the two share the
   check.
4. **`load_target(target, *, reload=False)`**. With `reload`:
   - a module target (`where` has no `.py` and no path separator) first
     deletes from `sys.modules` every key equal to `where` or starting
     with `where + "."`, then imports;
   - a file target executes afresh as `_load_file` already does, its
     `sys.modules[stem]` entry replaced;
   - `linecache.checkcache(path)` for the module's `__file__` and, for
     a package, each purged module's file, so `inspect.getsource`
     reads the new text.
   A failed load leaves `sys.modules` as the failure found it (22
   §Reloading a module): the file path's half-built entry is popped as
   today; the purge of a module target is not undone.

### The server

5. **Targets.** `Server.register(wf, pool=None, *, target=None)` records
   `target` in `self._targets: dict[str, str | None]` beside
   `_workflows`; `server.targets` returns a copy in registration order.
   `athanore serve` passes each positional as given; `discovered()`
   returns `(Workflow, target)` pairs where the target is the entry
   point's `value` (`module:attr`), and `serve` passes it through.
6. **`register` after `start()`** raises `RuntimeError("the server is
   serving; use add()")` (D226). `self._serve_task is not None` is the
   predicate `start()` already uses.
7. **`await Server.add(wf, pool=None, *, target=None)`**: the checks
   `register` makes (verb, pool-name, duplicate, `finalize`,
   `collect`/`validate`), each raising `LoadError` with its stage and the
   original message as `detail` (a `GraphError` from `finalize` →
   `finalize`; `PluginValidationError` → `plugins`; the name refusals →
   `register`). Then, in order: `engine.register(graph, pool)`;
   `_workflows`/`_targets`/`_specs` updated; if serving,
   `app.state.plugins.add(spec)` (T084), `await recover(engine,
   [name])` (T083), the `workflow.registered` event in its own uow,
   `engine.notify()`. Before `start()` the engine and the lists are
   updated and nothing else happens, which is what `register` does, so
   `register` becomes `add`'s synchronous pre-start subset rather than
   a second implementation.
8. **`await Server.replace(wf, pool=None, *, target=None)`**: the name
   must be registered (`LoadError(stage="register")` otherwise); the
   same validation; `engine.replace(graph, pool)` (T083 — its
   `ValueError` for a pool move with attempts in flight and its
   `KeyError` for an unknown pool are re-raised as they are; T086 maps
   them); `_workflows`/`_targets` updated and the spec replaced in
   `_specs` at its index; if serving, `app.state.plugins.replace(spec)`,
   `workflow.replaced`, `notify()`. A `target=None` on `replace` keeps
   the recorded target — the API's "reload what you loaded" passes the
   recorded one explicitly, but a host that replaces with an object it
   built should not lose the record.
9. **`await Server.remove(name) -> RemovedWorkflow`**: registered or
   `LoadError(stage="register")`; `task_ids = await
   engine.unregister(name)` (T083); the three lists drop the name; if
   serving, `app.state.plugins.remove(name)` and
   `workflow.unregistered {workflow, task_ids}`. `RemovedWorkflow` is a
   frozen dataclass `(workflow: str, task_ids: tuple[int, ...],
   persisted: Path | None)`, and `add`/`replace` return `Registered
   (name: str, persisted: Path | None)`; both are declared in
   `plugins.discovery` beside `LoadError` so that T086's API tier can
   name them without importing the composition root.
10. **Emitting.** The three events are written through
    `store.uow()` with `run_id=None`, `task_id=None` — the shape
    `Engine._announce_stopping` uses — only when `self._serve_task is
    not None`. The order within a verb is the order 22 §Effects lists:
    engine, mount, recovery, event, notify.

### Persistence

10a. **`[workflows.<name>].target`** is a known key. `cli.serve.layout`
    (or its successor in `plugins.discovery` — move `_bindings` there
    too so that the host and the CLI read the table through one
    function) returns, per name, the pool binding *and* the target
    when present. Unknown keys inside a row stay an error (02).
10b. **Boot order in `serve`**: positionals, then rows with a target,
    then entry points. A row whose loaded workflow's name is not its
    key is exit 2 naming the key, the name and the target. A row whose
    name a positional already registered is skipped with a warning
    naming both targets. A discovered workflow whose name a row
    registered is dropped exactly as one a positional registered is
    (11 §Server step 2) — extend that check from "the targets" to "the
    targets and the rows". Rows are registered with their target and
    pool recorded.
10c. **`Server.register_configured(root_path=None)`**: reads the same
    table (resolved as the settings source resolves `athanore.toml`,
    `root_path / "athanore.toml"`) and `register`s each row's workflow
    with its target and, when the row names one, `Pool` by that name
    looked up on the engine — a pool the host has not added is a
    `ValueError` naming the known pools, the same refusal `serve`
    prices at 2. Sync, before `start()`; `serve` uses it for step 10b's
    middle stage so there is one implementation.
10d. **`plugins/persist.py`**: `write_row(path, name, target, pool)`
    and `remove_row(path, name)` over `tomlkit` (new dependency, D228;
    add it to `pyproject.toml` and 02 §Library choices). `write_row`
    parses the file if it exists (a missing file becomes a document
    holding only `[workflows]`), sets `doc["workflows"][name]` to an
    inline table `{target = ..., pool = ...}` with `pool` only when
    given, and writes the file back; every other byte of the file —
    comments, ordering, the other rows' formatting — is preserved.
    `remove_row` deletes the key and is a no-op when it is absent; an
    empty `[workflows]` table is left in place. Both raise
    `PersistError(path, detail)` on an unreadable, unparsable or
    unwritable file. Nothing here imports `tomlkit` anywhere else in
    `athanore/`.
10e. **`persist=False`** on `add`, `replace`, `remove`. With `True`:
    `add`/`replace` require a `target` (`ValueError` otherwise) and
    call `write_row` **after** every validation of step 7/8 and
    **before** the engine step; `remove` calls `remove_row` before
    `engine.unregister`. A `PersistError` therefore leaves the server
    untouched, which is the whole reason for the order. The path is the
    settings' `root_path / "athanore.toml"`.
10f. **Never the source.** Assert in a test that no verb opens a `.py`
    for writing; there is no code path that could, and the test keeps
    it that way.

### The events

11. `EventName.workflow_registered = "workflow.registered"`,
    `workflow_replaced`, `workflow_unregistered` under a `# Workflows`
    comment in `athanore/events/names.py`. Payload models
    `WorkflowRegistered {workflow: str, pool: str, target: str | None}`
    (serialised without `target` when `None` — 18 §Envelope's "nothing
    is null-filled"; follow how existing optional payload fields do
    it), `WorkflowReplaced` (same fields), `WorkflowUnregistered
    {workflow: str, task_ids: list[int]}`; envelope classes and the
    three `Annotated[..., Tag(...)]` entries in the union in
    `athanore/events/payloads.py`. The docstring's "absent on
    `engine.*`" becomes "absent on `engine.*` and `workflow.*`".
12. **Snapshot and client.** The envelope union is in
    `tests/snapshots/openapi.json` via `GET /api/runs/{id}/events`, so
    this task runs `uv run scripts/dump_openapi.py && pnpm -C web gen`
    and commits both. Nothing in `web/src` outside `api/gen` changes.

### The folds

13. 03 §Event vocabulary: three rows. 18: the §Envelope sentence and a
    `### Workflows` table after §Engine. 04 §Programmatic host: the
    three coroutines and `register_configured()` under the existing
    snippet, one paragraph pointing at 22 §Server surface. 11 §Server:
    `load_target`'s new home and the factory form; the recorded
    targets; the boot order with rows as its middle stage and the two
    shadowing rules. 09 §Discovery: a discovered workflow's target is
    its entry point's value; a row shadows a discovered workflow like a
    target does; the toml example gains a `target` row. 02
    §`athanore.toml` layout: the `target` key in the example and the
    sentence that a row with one is a registration; §Library choices:
    `tomlkit`.

## What this task is not

- No route, no registrar port, no `WorkflowOut.target`, no CLI verb:
  T086. `athanore workflows reload` does not exist yet, and nothing in
  this task reads HTTP.
- No SPA change beyond the regenerated client.
- No engine or plugin-host behaviour beyond calling what T083 and T084
  built; if a call turns out to need something they did not provide,
  that is a gap in those tasks to fix on this branch and note in their
  plan files, not a reason to reach around them.
- No persistence anywhere but the toml row (D220): no database table,
  no `.athanore/` file. No file watcher (D222). No write to any `.py`.
- No change to `Workflow.run()`.

## Tests

- `tests/cli/test_discovery.py` (loader): a file target written to
  `tmp_path` loads; rewritten and loaded with `reload=True`, the new
  module's attribute is the new object and `inspect.getsource` shows
  the new text; a module target under a `tmp_path` package on
  `sys.path` with a submodule: after `reload=True` both module objects
  are new and a sibling module's object is the same one; each of
  `target`, `import`, `attribute` raises `LoadError` with that stage
  and the original message in `detail`; a factory attribute loads;
  `discovered()` pairs each workflow with its entry point's value
  (the existing entry-point fixture).
- `tests/cli/test_serve.py`: `serve` records targets (the positional
  string; the row's target; the discovered value); exit 2 and the same
  messages for a bad target; a row loads and is bound to its pool; a
  row whose key is not the workflow's name is exit 2 naming both; a
  positional and a row of one name → the positional, one warning; a
  row and a discovered workflow of one name → the row.
- `tests/test_persist.py` (new): on a `tmp_path` toml with comments,
  a `[pools]` table and two existing rows — `write_row` adds a third
  and the file differs by exactly that line; `write_row` on an
  existing name replaces its inline table only; `pool` absent when not
  given; a missing file is created with just the table; `remove_row`
  deletes only the row, and is a no-op for an absent one; a read-only
  file raises `PersistError`. `Server.register_configured()` on the
  same file registers the rows with targets recorded and refuses an
  unknown pool.
- `tests/test_server.py`: on a started `Server` with `MockAgent`
  bodies — `add` mounts (the plugin route answers), resets a row left
  `in_progress` under that name by a prior `remove`, emits
  `workflow.registered` then `engine.recovered` with `run_id` absent,
  and a run submitted afterwards dispatches; `replace` emits
  `workflow.replaced`, the running attempt completes on the old body,
  the next task on the new; `remove` returns the interrupted ids,
  emits `workflow.unregistered` naming them, the route is 404, the
  run reads `unregistered: true`; `register` after `start()` raises
  `RuntimeError`; before `start()` the three coroutines change
  `workflows`/`targets` and the events table stays empty; every
  `LoadError` stage the verbs raise (`finalize`, `plugins`,
  `register` ×3); `targets` is in registration order with `None` for a
  programmatic registration; `add(persist=True)` without a target
  raises `ValueError`; `add(..., persist=True)` writes the row and the
  workflow is registered, a failing validation writes nothing, a
  `PersistError` (read-only file) registers nothing; `remove(persist=
  True)` removes the row; no `.py` under `tmp_path` changed mtime or
  content across the whole test (a fixture that hashes them).
- `tests/test_events_names.py` and the payload contract test: pick up
  the three names automatically; add the "no `run_id`" assertion for
  `workflow.*` beside the one for `engine.*`.
- `tests/test_openapi_snapshot.py`: regenerated snapshot matches.

## Verification

```sh
./scripts/test.sh -k "discovery or serve or server or persist or events or snapshot"
uv run scripts/dump_openapi.py && pnpm -C web gen
git diff --exit-code tests/snapshots web/src/api/gen   # after committing the regen
./scripts/test.sh
```

## Done

- `Server.add/replace/remove/targets` work on a serving process with
  22 §Effects' sequence and events, and persist to and from
  `athanore.toml` on request; `athanore serve` and
  `register_configured()` load `target` rows with the stated
  precedence; `load_target` lives in `plugins.discovery`, reloads a
  module subtree and a file, and names its stage; the three events
  exist end to end through the snapshot and the generated client;
  folds landed; gate green.
