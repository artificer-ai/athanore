# Writing a plugin

A plugin is not a separate artefact. **The workflow is the host**: the
same object that carries your nodes carries the declarations, and
installing the workflow installs its interface. The built-in operator
views are declared the same way, through the same four decorators.

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

## The four declarations

- **`@wf.route`** mounts an HTTP endpoint under your workflow's own
  prefix. It is an operator route like any other and hangs on the same
  door. The `ctx: PluginContext` parameter becomes a dependency resolved
  from the request's `run_id`, `task_id` and `node` query parameters;
  every other parameter follows the usual rules, so a `limit: int = 50`
  is a documented query parameter with a default.
- **`@wf.action`** is a named operation you can invoke from the
  interface. Its pydantic input model *is* its form — there is no
  separate form to build.
- **`wf.panel(...)`** declares a pane or a card. It is a plain call, not
  a decorator, because it declares data and has no function to wrap.
- **`@wf.on(...)`** subscribes to engine events, and is called after the
  transaction that emitted one has committed.

Every field of every declaration, and the closed vocabularies for slots,
placements, panel kinds and route methods, are in
[Plugins](../reference/plugins.md).

## Panels are data; the renderer stays in the interface

A panel names a `kind`, and each kind fixes what its `source` route has
to return: prose for `markdown`, a mapping for `kv`, columns and rows
for `table`, timestamped lines for `log`, series for `chart`, metric
tiles and an optional table for `dashboard`, an action name for `form`.
A plugin therefore ships no JavaScript at all unless it chooses to. A
kind that is not recognised renders a placeholder card rather than
breaking the page.

`slot` says where a panel shows: on the selected run, on a task, on a
node (live only while that node has work in flight or has produced
output), on the workflow's page in the library, or globally when no run
is selected. `refresh_on` names the events that make it refetch.

## Scope follows ownership

A workflow's run panels show on its runs, its actions validate only
against its runs, and its routes mount under its own name. An id
belonging to somebody else's workflow is answered as missing, not as
forbidden: it is not yours to know about.

`PluginContext` carries the ids, the resolved run and task rows when
they are in scope, the same narrow services a node body gets, and the
operator operations. Each service says which ids it needs. `log`,
`stream`, `submissions` and `requests` belong to the *attempt* in scope
and refuse without a task — so the `override` action above is
`scope="task"`, because it appends to an attempt's work log. `run.get`,
`run.detail`, `run.log_entries` and `run.events` need only a run. In
workflow or global scope there is neither, and all of those refuse where
they are reached for, while listing your workflow's runs, publishing
your own events and the operator operations — which take explicit ids —
work in every scope.

Your handler takes `ctx` explicitly. It is never injected by parameter
name, because a node's parameters already mean edges and one meaning per
signature is why the graph reads the way it does.

## The escape hatch

When no built-in kind fits, declare a `custom` panel naming a web
component of your own, and point the workflow at a directory of assets:

```python
from athanore import Workflow

wf = Workflow("gamedev", assets="./static")

wf.panel("Playfield", slot="task", node="qa", kind="custom", element="gd-playfield")
```

`./static` is served under your workflow's own asset prefix with a
strict content-security policy and no inline scripts. The element gets
the ids in scope as attributes and calls back to your own routes through
the bridge the interface exposes. One file of browser JavaScript, no
build step.

If you need a library from a CDN, the deployment allows specific origins
through `plugin_cdns`; see [Settings](../reference/settings.md). The
policy for connecting back is never widened, so a CDN script may run but
can only talk to the server that served the page.

## Your own events

A workflow may publish events under its own name, through
`ctx.services.events.publish`, and subscribe to the engine's vocabulary
with `@wf.on(...)`. The names the engine publishes are in
[Events](../reference/events.md).

## Getting it installed

A packaged workflow advertises itself as an entry point, and then a bare
`athanore serve` finds it:

```toml
[project.entry-points."athanore.workflows"]
gamedev = "acme.flows:gamedev"
```

The entry-point name on the left is what the distribution called it; the
name runs are submitted under is the workflow's own. They are usually the
same and nothing requires it.

Naming a target explicitly on the command line wins over a discovered
workflow of the same name, which is how you serve a working copy of an
installed workflow without uninstalling it. An entry point that cannot be
loaded stops the server and names itself, its distribution and the cause
— a workflow that is definitely installed should not next be observed as
a 404.

Installing a workflow package means running its Python on your server and
its browser code in your session with your credentials. That is one trust
decision, made when you install it.

## Next

- [Plugins](../reference/plugins.md) — the declarations and the context,
  field by field.
- [Driving the API](http-api.md) — where your routes end up, and how the
  manifest reaches the interface.
