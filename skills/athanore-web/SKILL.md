---
name: athanore-web
description: Change the Athanore SPA in web/ — the one-screen layout and its pane cycle, SSE-driven cache invalidation, the keyboard map, plugin panel renderers, and the generated design tokens and API client that are never hand-edited. Load this before editing anything under web/, or when deciding whether a change belongs in the SPA at all.
---

# Working on the Athanore SPA

This skill is for a contributor to the SPA itself, so unlike its four
siblings it points into the checkout: every path below is relative to
the checkout root, two levels above this file, and `AGENTS.md` there is
how to work in the repository — read it first. The SPA in `web/` is the
operator interface, and it is the only one.

## The surface

1. **One screen, with a pane cycle.** Not a router full of pages: a
   single operating surface whose regions change what they show. The
   cycle lives in `web/src/panes/`, with one renderer per pane kind
   under `web/src/panes/kinds/`.
2. **Realtime is server-sent events invalidating query caches**, never
   a second copy of the server's state kept in the browser. Nothing
   polls: `web/src/realtime/sse.ts` consumes the stream and
   `web/src/realtime/invalidate.ts` is the table saying which event
   makes which query stale. A view that goes stale is a row missing from
   that table.
3. **The design system is generated from the mock's tokens.**
   `web/src/styles/theme.css` is written by `pnpm -C web gen:theme` from
   the design mock's stylesheet; `AGENTS.md` says where the mock and the
   normative design document are.

## The commands

<!-- from: AGENTS.md -->
```sh
pnpm -C web install
pnpm -C web typecheck && pnpm -C web lint && pnpm -C web test && pnpm -C web build
```

The Playwright suite drives the built SPA against a real server with a
fake agent behind every agent, and it is the fastest way to see what a
change looks like from outside:

<!-- from: AGENTS.md -->
```sh
pnpm -C web exec playwright test           # all of web/e2e
pnpm -C web exec playwright test run.spec.ts --workers=1
```

## The rules an agent gets wrong first

- **Two files under `web/` are generated, and hand-editing either is
  a red gate**: `web/src/api/gen` from the committed OpenAPI snapshot by
  `pnpm -C web gen`, and `web/src/styles/theme.css` by
  `pnpm -C web gen:theme`. A route change means regenerating the client,
  not patching it; a colour change means changing the mock's tokens.
- **A workflow's own view is a plugin panel, not a change to the SPA.**
  If the change you are about to make is one workflow's pane or button,
  it belongs to that workflow's declarations — the `athanore-plugins`
  skill — and the SPA already renders every panel kind.
- **Adding a pane kind is a change to the renderer vocabulary** shared
  with the server's plugin declarations, not a local addition; the
  `custom` kind, drawn by `web/src/panes/CustomElementHost.tsx` through
  the bridge in `web/src/plugins/bridge.ts`, is the escape hatch for a
  panel no kind fits.
- **The event union and the client are in `web/src/api/gen`.** Every
  query key the invalidation table uses is built by a generated helper,
  so a key written by hand is one the table cannot reach.
- **Keyboard bindings are scoped**: `web/src/keys/` is the map and the
  scoping, and a binding is live only in the scope it belongs to. The
  typing check walks the event's composed path, so a keystroke inside a
  plugin's shadow root is still a keystroke in a field.
- Overlays — the palette, the new-run form, the task drawer, the
  library — are under `web/src/overlays/`, and `web/e2e/` is where a
  new behaviour gets its end-to-end test.

## Where things live

- `web/src/panes/` — the cycle, the pane bar, the panel cards and the
  manifest; `web/src/panes/kinds/` — one file per renderer.
- `web/src/realtime/` — the SSE consumer and the invalidation map.
- `web/src/plugins/` — the manifest, the renderer registry, the asset
  loader and the bridge a custom element talks to.
- `web/src/keys/` — the keyboard map and its scoping.
- `web/src/overlays/` — everything that opens over the screen.
- `web/src/api/client.ts` — how the SPA configures the generated
  client; `web/src/api/gen/` is the generated part.
- `web/e2e/` — the Playwright suite.

This skill has no `reference/` directory, deliberately: the SPA's facts
are TypeScript, already generated and gated where they can be. The
event names it subscribes to, with their payloads, are in the
`athanore-workflows` skill's reference; the endpoints behind the
generated client are in the `athanore-api` skill's.
