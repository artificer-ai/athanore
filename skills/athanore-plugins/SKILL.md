---
name: athanore-plugins
description: Give an Athanore workflow its own UI and endpoints — routes, actions, panels and event handlers, the panel kinds, the scopes a handler is resolved in, PluginContext, and the custom web-component escape hatch. Load this before adding a pane, an operator button or an HTTP endpoint to a workflow, or when a plugin handler is being refused and you need to know why.
---

# Writing an Athanore plugin

Every path in this file is relative to the **checkout root**: the
directory two levels above this file in the checkout this skill was
installed from. Nothing here is normative — `docs/v1/09-plugins.md` is
the specification and this only says which part of it to open.

## The surface

A plugin is not a separate artefact. **The workflow is the host**: the
same `Workflow` object that carries the nodes carries the declarations,
and installing the workflow installs its UI. Three ideas are the whole
of it:

1. **Four declarations, and nothing else crosses the wire.** A route, an
   action, a panel and an event handler are data; the *renderer* stays
   in the SPA, so a plugin ships no JavaScript unless it chooses to:
   `docs/v1/09-plugins.md` §Declarations.
2. **Scope follows ownership.** A workflow's panels show on its runs,
   its actions validate against its runs, and its routes mount under its
   name. An id belonging to somebody else is not visible, which is why
   it is answered as missing rather than as forbidden:
   `docs/v1/09-plugins.md` §Context and scopes.
3. **`PluginContext` is the one thing a handler is handed.** It is an
   explicit parameter and never signature injection — a node's
   parameters already mean edges, and one meaning per signature is the
   whole reason the graph reads the way it does.

## The seams

- **`@wf.route`** — an HTTP endpoint mounted under this workflow's own
  prefix: `docs/v1/09-plugins.md` §Mounting.
- **`@wf.action`** — a named operation the operator can invoke, whose
  pydantic model *is* its form.
- **`wf.panel(...)`** — a pane or a card, declared as data. Which kinds
  exist, and what a panel's source must return for each, is
  `docs/v1/09-plugins.md` §Panel kinds (the renderer vocabulary).
- **`@wf.on(...)`** — a handler called after the transaction that
  emitted an event has committed.
- **Slots and placement** — where a panel appears, and when a
  node-scoped one is live: `docs/v1/09-plugins.md` §Slots.
- **The `custom` panel kind, with `assets=`** — a web component of your
  own when no built-in kind fits, reaching the API through the bridge
  the SPA exposes: `docs/v1/09-plugins.md` §Escape hatch: web components.
- **`ctx.services` and `ctx.ops`** — the same narrow services a node
  body gets, plus the operator operations.
- **The `plugin.` event namespace** — a workflow may publish its own
  events, under its own name and nowhere else:
  `docs/v1/18-event-payloads.md` §Plugins.
- **Entry-point discovery** — how an installed package advertises a
  workflow so a bare `athanore serve` finds it:
  `docs/v1/09-plugins.md` §Discovery.

## Where to read

| If you are asking | Open |
|---|---|
| which of the four declarations do I want? | `docs/v1/09-plugins.md` §Declarations |
| what must a panel's `source` return for this kind? | `docs/v1/09-plugins.md` §Panel kinds (the renderer vocabulary) |
| where will this panel appear, and when is a node slot live? | `docs/v1/09-plugins.md` §Slots |
| what does a handler get in `workflow` or `global` scope, and which services refuse there? | `docs/v1/09-plugins.md` §Context and scopes |
| why is an id I do not own a 404 and never a 403? | `docs/v1/09-plugins.md` §Context and scopes |
| what is rejected at registration, and when? | `docs/v1/09-plugins.md` §Registration and validation |
| what path does my route end up on? | `docs/v1/09-plugins.md` §Mounting |
| how does a custom element reach my routes? | `docs/v1/09-plugins.md` §Escape hatch: web components |
| what does the manifest look like on the wire? | `docs/v1/09-plugins.md` §Wire contract |
| how is a plugin authenticated? | `docs/v1/12-security.md` §Plugins |
| what may a plugin event be called, and what may it carry? | `docs/v1/18-event-payloads.md` §Plugins |
| how does the SPA render any of this? | `docs/v1/10-frontend.md` §Plugin renderers |
| how does a packaged workflow get discovered? | `docs/v1/09-plugins.md` §Discovery |
| what is deliberately not a seam yet? | `docs/v1/09-plugins.md` §Later seams |

A plugin has no authentication model of its own: a plugin route is an
operator route and hangs on the API's own door. `docs/v1/12-security.md`
§Plugins is the whole of it, and it is short.

## What to copy

- `athanore/plugins/builtin/` — the built-in panes are themselves
  plugins, declared through the same four decorators:
  `docs/v1/09-plugins.md` §Builtins are plugins. Read these first; they
  are the reference implementation of every kind.
- `workflows/feature/files.py` — four routes and two `custom` panels,
  which is the escape hatch end to end.
- `workflows/feature/static/files.js` — the other side of that escape
  hatch: the custom element itself, and how it calls back.
- `workflows/feature/cron.py` and `workflows/feature/static/cron.js` —
  the same shape again, with a background ticker behind it.

The two shapes, from `workflows/feature/files.py`. A route is a
decorated function taking the context:

<!-- from: workflows/feature/files.py -->
```python
@wf.route("/files")
async def files_list(ctx: PluginContext) -> list[dict[str, Any]]:
    """Every file in the drop box, newest first."""
```

...and a panel is data, naming the element that draws it:

<!-- from: workflows/feature/files.py -->
```python
wf.panel(
    "files",
    slot="global",
    kind="custom",
    element="athanore-files",
)
```

## Generated reference

Facts, read off the code by `scripts/gen_skills.py`, so they cannot
drift from it:

- `skills/athanore-plugins/reference/declarations.md` — the four
  declarations field by field, the slot and panel-kind vocabularies, and
  the methods a route may declare.
- `skills/athanore-plugins/reference/context.md` — what is on
  `PluginContext`, every service and its methods, and the two refusals a
  handler gets for reaching outside its scope.

The event names an `@wf.on(...)` may subscribe to are
`skills/athanore-workflows/reference/events.md`, and the error shape a
refusal is reported in is `skills/athanore-api/reference/error-codes.md`.
