---
name: athanore-plugins
description: Give an Athanore workflow its own interface and endpoints — routes, actions, panels and event handlers, the panel kinds, the scopes a handler is resolved in, PluginContext, and the custom web-component escape hatch. Load this before adding a pane, an operator button or an HTTP endpoint to a workflow, or when a plugin handler is being refused.
---

# Writing an Athanore plugin

A plugin is not a separate artefact. **The workflow is the host**: the
same `Workflow` object that carries the nodes carries the declarations,
and installing the workflow installs its interface. Four declarations
cross the wire — a route, an action, a panel and an event handler — and
they are data; the renderer stays in the interface, so a plugin ships
no JavaScript unless it chooses to. This directory is self-contained:
every file it names is under its own `reference/`.

## A complete plugin

A route, an action, a table panel fed by the route, and a handler:

<!-- from: docs/site/src/guide/plugins.md -->
```python
from typing import Any

from athanore import PluginContext, Workflow
from pydantic import BaseModel

wf = Workflow("gamedev", assets="./static")


class Override(BaseModel):
    word: str
    reason: str = ""


@wf.route("/words")
async def words(ctx: PluginContext, limit: int = 50) -> dict[str, Any]:
    """Every word this run has used, newest last."""
    entries = await ctx.services.run.log_entries()
    rows = [{"word": entry.text} for entry in entries[-limit:]]
    return {"columns": [{"key": "word", "label": "Word"}], "rows": rows}


@wf.action("override", scope="task", title="Override secret word", confirm=True)
async def override(ctx: PluginContext, input: Override) -> dict[str, Any]:
    await ctx.services.log.append(f"override: {input.word} ({input.reason})")
    return {"ok": True}


wf.panel("Words", slot="run", kind="table", source=words, refresh_on=["log.appended"])


@wf.on("run.completed")
async def done(ctx: PluginContext, event: Any) -> None:
    ...
```

The route mounts under the workflow's own prefix; `ctx` is resolved
from the request's `run_id`, `task_id` and `node` query parameters, and
`limit` is an ordinary query parameter with a default. The action's
pydantic model *is* its form, and it is `scope="task"` because it
writes an attempt's work log. The panel is a plain call, not a
decorator, because it declares data and has no function to wrap. This
is the interface half only: before `athanore serve` accepts it, give it
a start node (the `athanore-workflows` skill) and create the `./static`
directory `assets=` names, or drop that argument.

## The rules an agent gets wrong first

- **`ctx: PluginContext` is an explicit parameter, never injected by
  name.** A node's parameters already mean edges, and one meaning per
  signature is why the graph reads the way it does.
- **Scope follows ownership.** A workflow's panels show on its runs,
  its actions validate only against its runs, its routes mount under
  its name. An id belonging to another workflow is a 404, never a 403:
  it is not yours to know about.
- **Each service says which ids it needs, and refuses without them.**
  `log`, `stream`, `submissions` and `requests` belong to the *attempt*
  in scope and raise without a task, so an action that writes the work
  log is `scope="task"`, not `"run"`; `run.get`, `run.detail`,
  `run.log_entries` and `run.events` need only a run. In workflow or
  global scope there is neither. Listing your workflow's runs,
  publishing your own events and the operator operations — which take
  explicit ids — work in every scope.
- **The panel `kind` fixes what its `source` returns**: prose for
  `markdown`, a mapping for `kv`, columns and rows for `table`,
  timestamped lines for `log`, series for `chart`, metric tiles for
  `dashboard`, an action name for `form`. An unknown kind renders a
  placeholder card rather than breaking the page.
- **`slot` says where a panel shows** — the selected run, a task, a
  node (live only while that node has work in flight or has produced
  output), the workflow's page, or globally — and `refresh_on` names
  the events that make it refetch.
- **A `custom` panel with `assets=` is the escape hatch**: one file of
  browser JavaScript defining a web component, served under the
  workflow's own asset prefix with a strict content-security policy and
  no inline scripts. It calls back to your routes through the bridge
  the interface exposes. A library from a CDN needs its origin in
  `plugin_cdns`.
- **A workflow's own events go under its own name** through
  `ctx.services.events.publish`; `@wf.on(...)` subscribes to the
  engine's vocabulary and runs after the emitting transaction commits.
- **A packaged workflow advertises itself as an entry point** in the
  `athanore.workflows` group, and a bare `athanore serve` finds it.
- A plugin route is an operator route and hangs on the same door as the
  rest of the API; there is no authentication model of its own.

## Where to read next

Every file below is in this skill's `reference/`. The guide is
narrative; the three after it are generated from the code, so a field
or a default there is the one that runs.

- The four declarations, panels as data, scope, the escape hatch, your
  own events, getting it installed: `reference/guide-plugins.md`.
- Every field of `Route`, `Action`, `Panel` and `Handler`; the slot,
  placement, panel-kind and method vocabularies; every attribute of
  `PluginContext`, every service and its methods, `ctx.ops`, and the
  two refusals: `reference/plugins.md`.
- Every event name a handler may subscribe to, and the payload it
  carries: `reference/events.md`.
- Every setting, `plugin_cdns` among them: `reference/settings.md`.

The nodes the plugin hangs off are the `athanore-workflows` skill; the
API a custom element calls back to is the `athanore-api` skill.
