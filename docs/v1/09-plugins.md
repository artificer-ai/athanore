# 09 — Plugin system

Carried from `docs/design/plugins.md` (decisions taken, not implemented)
and finished. The workflow is the plugin host; Python describes UI as
data; the browser renders; the only code that crosses to the browser is a
static web component the plugin chooses to ship.

## Declarations

```python
from pydantic import BaseModel
from athanore import Workflow

wf = Workflow("gamedev", assets="./static")          # assets optional

class Override(BaseModel):
    word: str
    reason: str = ""

@wf.route("/words")                                   # GET /api/plugins/gamedev/words?run_id=…
async def words(ctx: PluginContext, limit: int = 50) -> dict: ...

@wf.action("override", scope="run", title="Override secret word", confirm=True)
async def override(ctx: PluginContext, input: Override) -> dict: ...

wf.panel("Words", slot="run", kind="table", source=words, refresh_on=["log.appended"])
wf.panel("Playfield", slot="task", node="qa", kind="custom", element="gd-playfield")

@wf.on("run.completed")
async def done(ctx: PluginContext, event: Event) -> None: ...
```

`panel` is a plain call, not a decorator: it declares data and has no
function to wrap (the earlier draft decorated an unused function, which
reads as if the body mattered). `route`, `action`, and `on` wrap the
handler they need.

| Declaration | What it is | Scope |
|---|---|---|
| `route` | a FastAPI path operation mounted under `/api/plugins/{wf}/` (`methods=` defaults to GET); `ctx: PluginContext` is a FastAPI dependency resolved from the `run_id` / `task_id` / `node` query parameters, and any other parameter follows normal FastAPI rules; data source for panels and custom elements; operator-authenticated | run / task / node / workflow / global via query ids |
| `action` | named handler + pydantic input model; the model **is** the form | `run` / `task` / `node` / `workflow` / `global` |
| `panel` | declarative: `slot`, `kind`, `source` (a route) or `element` (a custom tag), `refresh_on` events, optional `node` liveness | same as action |
| `on` | subscribe to engine events (the vocabulary in 03) | inherits the workflow |

`PluginContext`: `run_id`, `task_id`, `node`, `workflow`, resolved
`run`/`task` rows when in scope, `services` (the same narrow services
bodies get in `TaskServices`, 04: log, stream, submissions, requests,
run, plus `events.publish` for `plugin.*` names) and `ops` (the operator
operations in 04, so an action can pause, rerun, append a log entry).
Actions cannot route the graph or register nodes. Explicit `ctx`, not
signature injection — node parameters already mean edges.

Scope follows ownership: a workflow's run panels show only on its runs,
its actions validate only against its runs (a `run_id` of another
workflow is 404), its routes mount under its name.

### Panel kinds (the renderer vocabulary)

| kind | data shape from `source` | renders as |
|---|---|---|
| `markdown` | `string` | prose |
| `kv` | `dict` | description list |
| `table` | `{columns: [{key, label, kind?}], rows: [{…}]}` | data table with sorting |
| `log` | `[{ts, text, level?}]` | autoscrolling stream |
| `chart` | `{series: [{name, points: [[x, y]]}], kind: line\|bar}` | small chart (new; the MVP's stats bars) |
| `dashboard` | `{note?, metrics: [{label, value}], table?: {columns, rows}}` | the design mock's plugin pane: a note, metric tiles, a table (new) |
| `form` | an action name | the action's form + submit |
| `custom` | attrs from scope | the plugin's web component |

Unknown `kind` renders a placeholder card, never a crash.

### Slots

`run` (a pane in the selected run's cycle, `placement="pane"`, or a
card appended to the overview pane, `placement="card"`), `task` (the
task drawer), `node` (a run pane live only while the named node has a
task in flight or has produced output), `workflow` (the workflow
library's detail side), `global` (a pane shown when no run is selected).

Node liveness is computed server-side and travels on the per-run graph
response: `GET /api/runs/{id}/graph` marks each node `live` (08 §Graph
semantics). The manifest stays static; the SPA shows a `node`-slot pane
when the manifest entry's `node` is `live` in the selected run's graph,
and the pane count changes accordingly (10 §Panes clamps the index).

`PluginContext` by scope: for `run`/`task`/`node` scopes `run` (and
`task`) are resolved rows and every service is available. For `workflow`
and `global` scopes `run_id`, `task_id`, `run`, `task` are `None`;
`services.log`, `stream`, `submissions`, `requests` raise
`PluginError(400, "no run in scope")` where they are reached for, while
`services.run.list()`, `services.events.publish`, and `ops` (which take
explicit run/task ids) work. The four run-scoped services belong to an
*attempt*, so a run in scope without a task is
`PluginError(400, "no task in scope")` — the same refusal one level in.
`services.run.list()` lists the plugin's own workflow's runs and no
others. Handlers never get a partially-resolved context: a `run_id` that
exists but belongs to another workflow is a 404 before the handler runs,
as is a `task_id` of another run and a `node` the workflow does not have.

### Escape hatch: web components

`assets="./static"` (resolved relative to the module; package data when
installed) is served at `/plugins/{wf}/static/`. The manifest lists each
`.js` in it; the SPA injects them once as `<script type="module">`. A
`custom` panel renders `<the-tag run-id=… task-id=… node=…>` inside a thin
React wrapper. The element gets `window.athanore`:

```ts
window.athanore = {
  fetch(path, init)                     // bound to /api/plugins/{wf}/, carries auth
  subscribe(names: string[], cb)        // the SSE feed, filtered
  theme: { tokens }                     // CSS custom properties, pierce shadow DOM
}
```

Nothing else. Any framework may be used inside the element.

## Registration and validation

`server.register(wf)` collects declarations, then fails fast on six
things:

1. duplicate route/action/panel names within the workflow — routes clash
   on a path *and* a method, actions and panels on their name;
2. an action or panel whose scope names a node that does not exist, and a
   panel in the `node` slot or scope that names none;
3. a `custom` panel without an `element`;
4. a `source` that names nothing this workflow declared — a route for the
   data kinds, an action for `form`;
5. an `assets` directory that does not exist;
6. an `on` naming an event outside the vocabulary (`plugin.*` excepted,
   and a `plugin.*` name must be the subscribing workflow's own
   namespace).

Routers mount, the manifest entry is built. Errors at startup, never at
runtime — the same contract the graph has, and the refusal is a
`PluginValidationError` (`PluginError` carries an HTTP status and belongs
to a handler, not to registration).

## Wire contract

- `GET /api/plugins` → manifest: `[{workflow, panels: [{name, slot,
  placement, kind, scope, node?, source?, element?, refresh_on}],
  actions: [{name, title, scope, confirm, schema}], assets: [url]}]`.
  Fetched at boot and again whenever the SSE stream reconnects and
  `/api/me` reports a new `started_at` (the manifest only changes on
  restart, so no event is needed for it).
- `POST /api/plugins/{wf}/actions/{name}` → validates `input` against the
  model (422), resolves `ctx`, calls the handler, returns its JSON.
  Handlers may raise `PluginError(status, message)`.
- Plugin routes are ordinary FastAPI routes under the operator auth
  dependency; the manifest carries their paths so the SPA fetches them
  through the generated client's `fetch`.
- Events reach `on` handlers in-process after commit; a handler that
  raises is logged and does not affect the engine.

## Builtins are plugins

The core-shipped operator views are declared through the same API in
`athanore/plugins/builtin/` and appear in the manifest like anything else:

| Builtin | Declarations |
|---|---|
| `overview` | run pane (`dashboard`: metric tiles, token bars, `kv` meta, `table` nodes) |
| `log` | run pane `log` sourced from the work log + events, refresh on `log.appended` and `task.*` |
| `agent` | run pane `custom` `<ath-agent-stream>` reading `/api/tasks/{id}/stream` for the focused task, with the docked request panel |
| `requests` | run pane `custom` `<ath-requests>` (the mock's messages pane), plus a global pane when no run is selected |
| `graph` | run panel `custom` `<ath-run-graph>` (the rail-list renderer, shipped in the SPA bundle, not as a plugin asset) |

The SPA ships the renderers for these element tags itself; the point is
that their *placement and liveness* flow through the manifest, so the
host page has no hard-coded knowledge of them. That is the proof the API
is sufficient.

## Discovery

- Entry-point group `athanore.workflows`: each entry is `module:wf` (or a
  callable returning one). `athanore serve` registers all of them; a
  server flag disables discovery; `athanore serve pkg.mod:wf` registers
  explicitly. Pools come from `athanore.toml`:

```toml
[pools]
local = 1
cloud = 8

[workflows]
feature_build = { pool = "local" }
gamedev = { pool = "local" }
```

## Security (12 has the model)

Installing a workflow package means running its Python on the server;
its plugin JS runs in the operator's browser with the operator's token.
That is one trust decision, made at install time, and the docs say so.
Mitigations that are still worth having: plugin routes run under the same
auth as everything else; assets are served with a strict CSP
(`script-src 'self'`), no inline scripts; the manifest never carries
tokens; action inputs are validated server-side; a plugin cannot reach
another workflow's runs.

## Phasing

1. Declarations, registry, manifest, `panel` with the declarative kinds
   and `refresh_on`; the builtins declared through it from the first SPA
   commit (14: this is the start of the SPA phase, not after it, so the
   pane host is never written twice).
2. `route` + `action` + `ActionForm` in the SPA.
3. `assets` + `custom` + `window.athanore`.
4. Entry-point discovery; `athanore.toml` pools.

## Later seams

Standalone `Plugin` objects registered on the server without a workflow;
header status slot and per-row run-list annotations; `athanore plugins`
CLI verb; driving actions from the CLI (the JSON Schema is already there).
