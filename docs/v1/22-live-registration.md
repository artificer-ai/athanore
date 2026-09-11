# 22 — Live registration: workflows added, replaced and removed while serving

The second post-1.0 feature set. Today the set of workflows a server
runs is fixed when `start()` is called: `Server.register` refuses a name
it already has, `create_app` bakes the plugin routers and the manifest
in, and the only way to pick up an edited module is to stop the
process. This document makes the three registrations — add, replace,
remove — operations a running server performs, gives them a wire, and
names what happens to the runs in flight when it does.

Almost none of the *semantics* are new. The runner already resolves a
run's graph by name at every task dispatch (04 §Dispatch), a task whose
node the graph no longer declares already dead-letters (D42), and a run
whose workflow this process does not have is already left alone and
flagged `unregistered` (04 §Recovery on startup, 08 §Runs). Those rules
were written for the restart case; this document makes them fire live
and adds the one mechanism that is genuinely new — reloading a module
into a process that already imported it.

[`04-engine.md`](04-engine.md), [`08-api.md`](08-api.md),
[`09-plugins.md`](09-plugins.md), [`11-cli.md`](11-cli.md) and
[`18-event-payloads.md`](18-event-payloads.md) remain the specs for
their surfaces. This document is normative for the behaviour it adds;
the tasks that build it (T083–T087) fold the deltas back into those
documents' affected sections, each pointing here. Where this document
and one of them disagree afterwards, that is a bug in the fold, not a
choice.

## Why

The operator wants an agent — a chat seat over the operator API — that
can write a workflow, register it, run it, read what went wrong, edit
it, and run it again, without the loop passing through a process
restart that kills every other run on the server. Everything in that
loop except "register it" already exists on the wire. This is the
missing verb, built so that the SPA, the CLI and any agent get it the
same way (02 §One wire contract).

## Scope

In scope: `Server.add` / `replace` / `remove`; the engine and pool
registry changes they need; live mounting and unmounting of a
workflow's plugin routes, manifest entry, assets and `on` handlers;
loading and *re*loading a `module:wf` or `path.py:wf` target;
`[workflows.<name>].target` in `athanore.toml`, read at boot and
written on request; three operator routes and three CLI verbs; three
events; the SPA refreshing
its workflow list, its manifest and its pane cycle on them, and saying
so when a plugin's JavaScript has changed under it.

Out of scope, explicitly:

- **Persistence anywhere but `athanore.toml`.** A live registration
  survives a restart only if it is written as a `[workflows.<name>]`
  row with a `target` (§Persistence), and the API writes that row only
  when asked to. There is no registry table in the database (D220).
- **Creating or resizing pools.** Capacity is the host's decision (04
  §Pools). A live registration binds to a pool that exists.
- **A file watcher.** Reloading is an explicit verb. The caller knows
  when it has finished editing; a watcher does not, and a half-written
  file imported on save is a failure nobody asked for (D222).
- **Hot-swapping an attempt already running.** The body that is
  executing keeps executing (§Replace). Two-phase suspension is the
  later seam 04 §Durability posture already names.
- **A UI for registering.** The SPA reflects registrations; it does not
  perform them. The library overlay's controls are a later seam.
- **Reloading anything but the target's own module subtree.** A helper
  module the target imports from *outside* its own package stays as the
  process first imported it, until the process restarts (§Reloading a
  module).

## Terms

A **target** is the string that names a workflow to load:
`package.module:attr` or `path/to/file.py:attr` (11 §Server). A
registration **has** a target when it was loaded from one — by
`athanore serve`'s positionals, by an `athanore.toml` row
(§Persistence), by discovery (whose target is the entry point's
`module:attr` value), or by the API — and has none when a programmatic
host passed a `Workflow` object to `register`. `GET /api/workflows`
reports it as `target`, absent when there is none.

## Server surface

```python
server.register(wf, pool=None, *, target=None)   # before start(); sync; chains; unchanged otherwise
await server.add(wf, pool=None, *, target=None)  # any time; refuses a name already registered
await server.replace(wf, pool=None, *, target=None)  # any time; requires the name to be registered
await server.remove(name, *, persist=False) -> RemovedWorkflow  # any time; .task_ids are the attempts it interrupted
server.targets -> Mapping[str, str | None]        # registration order, as `workflows`
server.register_configured()                      # before start(); the `[workflows.<name>].target` rows (§Persistence)
```

`add` and `replace` take `persist=False` too. `persist=True` requires a
`target` — a `Workflow` object cannot be written to a file — and is a
`ValueError` without one. Each returns what it did: `add` and
`replace` a `Registered(name, persisted)`, `remove` a
`RemovedWorkflow(workflow, task_ids, persisted)`, where `persisted` is
the path of the row written or removed and `None` when no file was
touched.

`register` is the boot-time idiom and keeps its contract: sync, strict
about duplicates, returns the server. Calling it after `start()` raises
`RuntimeError` naming `add` — today that call silently mounts nothing,
which is a defect, not a feature to preserve (D226). The three coroutines are
the live verbs. Before `start()` they only touch the registries (there
is no application to mount into and no store to emit to); after it they
do everything §Effects lists. They are what the API calls, through the
registrar port (§Wire), and what a programmatic host calls from inside
its own loop.

Every refusal `register` makes, `add` and `replace` make too, before
anything is mutated: a name that is a CLI verb, a name that is a pool,
a graph that does not finalize, a plugin declaration that does not
validate (09 §Registration and validation, checks 1–6). `add` also
refuses a registered name; `replace` also refuses an unregistered one.

## Effects

What each verb does on a serving server, in this order. A refusal
happens before step 1 and leaves the server exactly as it was.

### Add

1. `engine.register(graph, pool)`: the graph is entered and the name is
   bound to `pool` — the named pool, else the default pool sized by
   `workers` (04 §Pools). The pool MUST already exist (§Pools).
2. The plugin spec is mounted: its router is included in the live
   application, its assets directory is served, its manifest entry
   appears after the entries already there, its `on` handlers join the
   one dispatcher (§Live mounting).
3. **Recovery for the name.** Rows of this workflow left `in_progress`
   or `waiting` — by a `remove` earlier in this process, or by a
   previous process that stopped while running code this one did not
   have until now — are reset to `ready` exactly as 04 §Recovery on
   startup does for every registered workflow at boot, and announced
   with the same `engine.recovered {task_ids}` event. Recovery filters
   by workflow already (`reset_for_recovery(workflows)`); this is that
   call with one name. Nothing of the name is in flight in this process
   at an `add` — a `remove` cancelled it — so no row is reset under a
   worker.
4. `workflow.registered` is emitted, and the scheduler is notified.

### Replace

1. The new graph replaces the old under the same name. The pool binding
   is kept unless a pool is given; a *different* pool is refused with
   `409` while any attempt of the workflow is in flight, and rebinds
   the name otherwise (§Pools).
2. The old plugin spec is unmounted and the new one mounted in its
   place — same position in the manifest, same prefix, the new routes,
   the new assets, the new handlers.
3. `workflow.replaced` is emitted, and the scheduler is notified. No
   recovery runs: a registered name's orphaned rows were reset at boot
   or at its `add`, and the rows in flight belong to attempts that are
   still running.

**Attempts in flight finish on the body they started.** A running node
holds its `Node` and the function it wraps; nothing reaches into a
coroutine to change what it is executing, and the old module object
stays alive for as long as a function of it is referenced. **The next
task of every run dispatches on the new graph**, because the runner
looks the graph up by name at claim time and always has. A task whose
node the new graph does not declare dead-letters with the existing
`GraphError` (D42), and the operator moves it or reruns as today. This
is exactly what editing the code and restarting the server does, which
is the point: one behaviour for "the code changed", not two.

### Remove

1. Every attempt of the workflow this process is running — a task
   `in_progress`, or `waiting` on a `human_input` — is cancelled the
   way 04 §Shutdown cancels: the asyncio task is cancelled, the agent
   subprocess is terminated and after the grace period killed, the
   transcript is flushed, the stats entry is written as it is for any
   cancellation the façade sees (`status=failed reason=shutdown`, 05
   §Stats entry — the `workflow.unregistered` event is what says why),
   and **no task status is written**. The rows stay `in_progress` / `waiting`, which is what
   Add step 3 resets on the next registration of the name and what
   04 §Recovery on startup resets if the next process has the code.
   Their run is not touched either: it reads `running` and
   `unregistered: true`, which is the honest report — there is work
   here and no code for it.
2. The graph is removed and the name unbound from its pool. The pool
   stays: it is capacity the host declared, and other workflows may be
   on it. Queued and ready tasks of the workflow are never claimed
   again, because the claim filters by the pool's bound workflows (04
   §Dispatch order); they sit visibly in runs flagged `unregistered`.
3. The plugin spec is unmounted: routes answer 404 `not_found` like any
   path nobody serves, the manifest entry is gone, assets are no longer
   served, the handlers no longer receive events.
4. `workflow.unregistered {workflow, task_ids}` is emitted, naming the
   attempts step 1 interrupted.

Nothing is deleted. A run of a removed workflow is still listed, still
readable, still `rm`-able by the operator, and still resumable by
adding the workflow back. `remove` refuses nothing on account of what
is running: a `DELETE` that fails because a node happens to be mid-turn
is a `DELETE` the caller retries in a loop, and the code being gone is
the same fact either way (D221).

### Pools

A live registration names a pool by name, or none. Given, it MUST exist
on the engine — the API answers `422 unknown_pool` naming the known
ones, the same refusal 11 §Server prices at exit 2 for a binding in
`athanore.toml`. Omitted, `replace` keeps the binding the name has and
`add` uses the default pool. `athanore.toml`'s `[workflows]` bindings
are read at `athanore serve` time and are not consulted by a live
registration: the caller that wants the toml binding passes it (D223).

Moving a name between pools while attempts of it are in flight is
refused (`409 conflict`), for the reason the pool registry already
gives: the leases those attempts hold belong to the pool they were
claimed on, and re-binding under them would charge one pool's work to
another's capacity.

## Live mounting

`create_app` today receives a tuple of specs and mounts them once.
After this document it receives — or builds — a live collection that
owns the mounting and is what `app.state.plugins` holds for the life of
the application. The manifest route, the actions endpoint and
`GET /api/workflows/{name}` read the collection's current specs on
every request, which is what they do now with the tuple; nothing that
reads `app.state.plugins` caches it.

Adding a spec includes its router into the running application and
appends its `StaticFiles` mount, both of which Starlette matches on the
next request; the SPA fallback was mounted as the router's fallback
rather than as a route precisely so that routes added after it are
matched first (08 §Static). Removing a spec removes every route whose
name is `plugin:{workflow}:…` and the assets mount at
`/plugins/{workflow}/static`. Either way the cached OpenAPI document is
dropped, so `GET /openapi.json` describes the routes that exist. The
handler dispatcher keeps one subscription and a mutable set of specs;
add and remove swap a workflow's handlers under it without the
subscription closing, so no event is missed across a swap.

The manifest's asset URLs carry a content version:
`/plugins/{wf}/static/panel.js?v=<first 12 hex of the file's sha256>`,
computed when the manifest is read, as the asset list itself already
is. A module the browser has already run
cannot be run again — `customElements.define` for the same tag throws —
so the SPA needs to know that the bytes behind a URL it injected have
changed, and a URL that changes when the bytes do is the whole of that
(§SPA).

## Reloading a module

`load_target(target)` moves from `athanore.cli.serve` to
`athanore.plugins.discovery`, beside the entry-point loader it already
resembles, so the API tier can reach it without importing the CLI. Its
behaviour on a first load is unchanged (11 §Server). Loading a target a
second time in one process is the new case, and it is what `replace`
through the API is for:

- A **file target** (`path/to/file.py:wf`) executes the file afresh
  into a new module object, as it does today; the `sys.modules` entry
  under the file's stem is replaced. The file's directory is already on
  `sys.path` from the first load.
- A **module target** (`pkg.mod:wf`) first removes from `sys.modules`
  the module itself and every module under it — every key equal to
  `pkg.mod` or beginning with `pkg.mod.` — and then imports it again.
  That is what makes a package workflow reload as a unit: editing
  `workflows/feature/agents.py` and reloading `workflows.feature:wf`
  picks the change up, because `workflows.feature.agents` was purged
  with its package. A *sibling* — `workflows.rps` — is untouched, and a
  helper the target imports from outside its subtree is not reloaded
  (§Scope). `importlib.reload` alone does neither of these things: it
  re-executes one module and leaves its submodules cached, which is the
  "I edited the file and nothing changed" every author of a reloader
  has met once (D224).
- Either way `linecache` is invalidated for the files involved, so
  `GET /api/workflows/{name}/source` — which reads through `inspect` —
  shows the text the process now runs.

A load that fails leaves `sys.modules` as the failure found it: a file
target's half-built module is removed (as today), and a module target's
purge is not undone — the old module objects the running attempts hold
are unaffected by what `sys.modules` says, and the *registered* workflow
is unchanged because the failure happened before step 1 of §Effects.
The next successful load fixes the cache.

A target's attribute may be a `Workflow` or a callable returning one,
as an entry point's value already may (09 §Discovery): a discovered
workflow's recorded target is its entry point's `module:attr`, and
reloading it has to accept what discovery accepted. `athanore serve
pkg.mod:factory` therefore works too, which costs nothing and removes a
difference between the two ways a workflow arrives.

The name a target resolves to is the `Workflow`'s own, not the
target's (09 §Discovery). `replace` through the API checks that the
loaded workflow's name is the name in the URL and refuses otherwise
(`409 conflict`): a target that now defines a differently named
workflow is a new workflow, and `POST` is how it arrives.

## Persistence

`athanore.toml`'s `[workflows]` table already binds a name to a pool
(02 §`athanore.toml` layout, 09 §Discovery). It gains one key,
`target`, and a row that has one **is a registration**:

```toml
[workflows]
feature = { pool = "checkout" }                       # a binding, as before
chat    = { target = "workflows/chat.py:wf", pool = "play" }
hello   = { target = "workflows/hello.py:wf" }        # default pool
```

**At boot.** `athanore serve` loads the rows with a `target` after the
positionals and before the entry points, through the same loader and
with the same price for a failure (exit 2, naming the row, the target
and the cause — 11 §Server). The three inputs are one list with a
precedence, not three mechanisms: a positional is a row for this
process only, a row is a positional written down, and a discovered
workflow is what an installed package contributes when neither names
its workflow — 11 §Server's "an explicit target wins" applies to a row
exactly as to a positional, so a row shadows a discovered workflow of
the same name and the discovered one is dropped. A row's key MUST be the loaded workflow's
name; a mismatch is a failure too, because the row is the registration
and a registration under the wrong name is a typo that would otherwise
register something the operator did not write down. A positional that
loads the same name wins and the row is skipped with a warning naming
both targets — the positional is 11 §Server's "working copy", and it
already wins over a discovered workflow for the same reason. A
programmatic host gets the same rows from `server.register_configured()`,
which reads the file the settings resolved (`root_path /
athanore.toml`) and calls `register` for each with its target and
pool. A file with no such rows registers nothing; a missing file is
not an error.

**On request.** `POST` and `PUT` take `persist: bool = false`; `DELETE`
takes `?persist=`. With it, the server writes the row —
`[workflows.<name>] = {target, pool?}`, `pool` present only when the
request named one, so a default-pool workflow stays on the default pool
if `workers` changes — or removes it. The file is edited in place with
`tomlkit`, which round-trips comments, order and formatting (D228); a
missing file is created holding the one table. Writing happens **after
the load and every validation and before anything is mutated**, so a
target that does not load is never written down and a row that is
written is always for a workflow that then registers; a write that
fails (`500 persist_failed {path, detail}`) leaves the server exactly
as it was. `remove(persist=True)` on a name with no row is not an
error: the state asked for is the state that results.

Without `persist`, the API and the CLI change nothing on disk. A
registration is live, and the caller who wants it kept says so — a
"let me try this" does not edit the operator's configuration (D220).

**Never the source.** No verb deletes or writes a workflow's `.py`. A
module may define several workflows, it may be under version control,
and unregistering a workflow and deleting its code are different
intents; the caller that means the second does it itself.

## Wire

Three routes join 08 §Workflows, operator-authenticated like the rest of
the router:

| Method | Path | Body → Response |
|---|---|---|
| POST | `/api/workflows` | `{target, pool?, persist?}` → 201 `WorkflowOut`; 409 `conflict` if the name is registered; 422 `workflow_load_failed` (below); 422 `unknown_pool`; 500 `persist_failed` |
| PUT | `/api/workflows/{name}` | `{target?, pool?, persist?}` → 200 `WorkflowOut`; 404 `unknown_workflow`; 409 `conflict` if the target's name differs, or the pool would move a workflow with attempts in flight; 422 as above; 500 `persist_failed`. `target` omitted re-resolves the registration's recorded target, and is 422 `workflow_load_failed` (`stage: "target"`) when the registration has none |
| DELETE | `/api/workflows/{name}?persist=` | → 200 `{workflow, task_ids}` — the attempts that were interrupted; 404 `unknown_workflow`; 500 `persist_failed` |

`persist` is §Persistence: `false` by default, and with it the row in
`athanore.toml` is written or removed before the registration changes.
A response that wrote or removed a row carries `X-Athanore-Persisted:
<path>`; one that touched no file carries no such header. A receipt
about the request belongs on the response, not on `WorkflowOut`, which
is a workflow.

`WorkflowOut` gains `target?: str`, absent for a programmatic
registration. The list and the single read are otherwise unchanged;
they were already answered from the engine's live registry.

The load failure body names where the load stopped, because the
caller — an agent, more often than not — is the one who has to fix the
file and try again:

```json
{"error": "workflows/chat.py has no attribute 'wf' (workflows/chat.py:wf).",
 "code": "workflow_load_failed",
 "target": "workflows/chat.py:wf",
 "stage": "attribute",
 "detail": "…the exception's text, or the GraphError / PluginValidationError message…"}
```

`stage` is one of `target` (the string is not `where:attr`, or there is
no recorded target to reload), `import` (the module or file would not
load), `attribute` (no such attribute, or not a `Workflow`), `finalize`
(a `GraphError` from `finalize()` — a graph that does not close, a
node that routes to nothing), `plugins` (a `PluginValidationError` — 09
§Registration and validation), `register` (a name that is a verb or a
pool). `detail` is the full message of the underlying error, untouched.
An `ImportError` raised by user code is `import`; a traceback is not
sent — it is in the server log at ERROR with the target, the same as a
discovery failure at boot (09 §Discovery).

`DELETE` answers 200 with a body rather than 204, because the body is
the point: the caller wants to know what it interrupted (D227).

The API reaches the server through a **registrar port** — a small
protocol declared in `athanore.api`, implemented by `Server` and handed
to `create_app` beside the engine and the store — so that the API
imports nothing above its tier (02 §Layering). An application built
without a registrar (the OpenAPI dump, a test that wants none) answers
the three routes `503 registration_unavailable`; every application a
`Server` builds has one.

These routes execute Python the caller named. That is not a new power:
the operator door already admits every plugin action, every operator
op, and — on a loopback bind — no credential at all, because the
process is the operator's (12 §Posture). The routes are operator
routes, sit behind `operator_auth` like the rest of `/api/workflows`,
and are not on the agent surface: a task token reaches nothing under
`/api/workflows` and never will. 12 §Plugins gains the sentence.

### Events

Three names join the vocabulary (03 §Event vocabulary, 18 §Payloads,
mirrored to the TypeScript union by the generator):

| Event | data |
|---|---|
| `workflow.registered` | `{workflow, pool, target?}` |
| `workflow.replaced` | `{workflow, pool, target?}` |
| `workflow.unregistered` | `{workflow, task_ids: [int]}` — the attempts §Remove step 1 interrupted |

None carries a `run_id`: like `engine.*`, they are about the server.
18 §Envelope's "present on every event except `engine.*`" becomes
"except `engine.*` and `workflow.*`". They are stored — they are part of
the audit trail and the SSE cursor needs their ids — and they reach
every `on` subscriber, as an event that names no run does (09
§Mounting). They are emitted only by a serving server: before `start()`
there is no store to keep them.

### CLI

`athanore workflows` stays the table it is. It grows three subcommands,
thin clients of the three routes (11 §Verbs):

```
athanore workflows add <target> [--pool NAME] [--persist]             → POST   /api/workflows
athanore workflows reload <name> [<target>] [--pool NAME] [--persist] → PUT    /api/workflows/{name}
athanore workflows rm <name> [--persist]                              → DELETE /api/workflows/{name}
```

`--persist` is the body's `persist`; the verbs print the path from
`X-Athanore-Persisted` when the response carries it.

A `workflow_load_failed` prints `stage` and `detail` and exits 2 — the
same price 11 §Exit codes puts on a target `athanore serve` could not
resolve, because it is the same mistake. `rm` prints the interrupted
task ids, one per line, so the operator sees what stopped.

`athanore serve` records the target of every workflow it loads —
each positional as given, each discovered entry point as its
`module:attr` value — so that `athanore workflows reload <name>` with
no target reloads what `serve` loaded.

## SPA

Three rows join the invalidation table (10 §Realtime and caching):
`workflow.*` invalidates the workflow list, the single-workflow and
source queries, the manifest, and the run list — whose `unregistered`
flag is computed per request (08 §Runs), so a removal that emits no
`run.*` would otherwise leave the row's marker for something unrelated
to draw (D253). That refetch is what refreshes the library overlay, the
new-run chip group, the palette's plugin rows, the selected run's pane
cycle — whose index 10 §Panes already clamps when the count changes —
and the `⊘` a run of a removed workflow carries on its row (10
§Attention).

A newly registered workflow's assets are injected as any workflow's are
at manifest load. A **replaced** workflow's assets are the one case the
document cannot follow: if the manifest now lists a URL for a workflow
whose previously listed URL was injected — same path, different `?v=` —
the SPA shows a persistent notice, `plugin code changed — reload the
page`, with a reload control, and keeps rendering the old element until
then. It never re-injects: the second `customElements.define` would
throw inside the plugin's module and the pane would draw nothing
(D225). A removed workflow's scripts stay loaded and inert; its panels
leave the cycle with its manifest entry.

## Testing

Per 13 §Pyramid, at the lowest layer that expresses each behaviour:

- **Engine**: `replace` swaps the graph the next claim dispatches on
  while the attempt in flight completes on the old body; a task whose
  node the replacement lacks dead-letters with `GraphError`; `remove`
  cancels the in-flight attempt (agent subprocess gone, stats row
  `failed/shutdown` — the façade's ordinary cancellation entry, §Remove
  step 1), writes no task status, unbinds the pool and
  leaves the pool; a later `add` of the name resets those rows and
  emits `engine.recovered`; pool rebinding refused with attempts in
  flight, accepted without.
- **Plugins**: a spec added after the application is built answers on
  its routes, appears in the manifest in order, serves its assets with
  `?v=`, and its `on` handler receives the next event; removed, its
  routes are 404 `not_found`, its entry and mount are gone, its handler
  receives nothing, and the subscription never closed across the swap;
  `openapi.json` reflects both; the builtins stay first throughout.
- **Discovery**: `load_target` on a file target loads a changed file;
  on a module target purges the subtree and not a sibling; a failing
  reload leaves the registered workflow untouched; `linecache` is
  refreshed.
- **API**: the three routes and every listed status, including the
  exact `workflow_load_failed` body per stage; `target` on
  `WorkflowOut`; the three events on `/api/events` with no `run_id`;
  `/source` shows the reloaded text; the no-registrar application's
  503; a task token is 401/403 on all three.
- **Persistence**: `serve` loads a row's target, refuses a key that is
  not the workflow's name, skips a row a positional shadows with a
  warning; `register_configured` does the same for a host;
  `persist: true` writes exactly one row and leaves the rest of the
  file byte-identical (comments included), a failing load writes
  nothing, a failing write registers nothing, `DELETE ?persist=true`
  removes the row and only the row; the `.py` is never touched.
- **CLI**: the three verbs against a served fake, exit codes included,
  `--persist` writing and printing the path.
- **SPA**: the invalidation rows; the notice appears for a changed
  `?v=` and not for a first injection or a removal.
- **Playwright**, on `FakeACPAgent`: write a workflow file, `POST` it,
  see it in the library, run it to completion; edit the file to rename
  its node, `PUT`, run again and watch the new node; `DELETE` while a
  run is mid-node and see the run flagged unregistered and the attempt
  stop; `POST` it back and see the run finish.

`tests/snapshots/openapi.json` and `web/src/api/gen/` change in T085
(the event union) and T086 (the routes), and in no other task of this
phase.
