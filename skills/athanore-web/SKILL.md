---
name: athanore-web
description: Change the Athanore SPA in web/ — the one-screen layout and its pane cycle, SSE-driven cache invalidation, the keyboard map, plugin panel renderers, and the generated design tokens and API client that must never be hand-edited. Load this before editing anything under web/, or when deciding whether a change belongs in the SPA at all.
---

# Working on the Athanore SPA

Every path in this file is relative to the **checkout root**: the
directory two levels above this file in the checkout this skill was
installed from. Nothing here is normative — `docs/v1/10-frontend.md` is
the specification and this only says which part of it to open.

## The surface

The SPA in `web/` is the operator UI, and it is the only one: there is
no second frontend. Three ideas are the whole of it:

1. **One screen, with a pane cycle.** Not a router full of pages: a
   single operating surface whose regions change what they show. The
   regions are `docs/v1/10-frontend.md` §Layout (from the mock); what a
   pane is, and the order they cycle in, is
   `docs/v1/10-frontend.md` §Panes (cycle order).
2. **Realtime is SSE invalidating query caches**, never a second copy of
   the server's state kept in the browser:
   `docs/v1/10-frontend.md` §Realtime and caching.
3. **The design system is normative and generated from the mock's
   tokens**: `docs/v1/10-frontend.md` §Design system (normative). What a
   call site may write for type is
   `docs/v1/21-design-refresh.md` §Type scale (normative).

## The seams — and what is not one

- **A plugin panel is how a workflow gets UI.** If the change you are
  about to make is a workflow's own view, it belongs to that workflow
  and not to the SPA: `docs/v1/10-frontend.md` §Plugin renderers, and
  `skills/athanore-plugins/SKILL.md`.
- **A pane kind is the renderer vocabulary.** Adding one is a change to
  the vocabulary in `docs/v1/09-plugins.md` §Panel kinds (the renderer vocabulary),
  not a local addition.
- **A custom element is the escape hatch**, for the panel that no kind
  fits: `docs/v1/09-plugins.md` §Escape hatch: web components.

**Two files under `web/` are generated, and hand-editing either is
always wrong**: `web/src/api/gen`, written from
`tests/snapshots/openapi.json` by `pnpm -C web gen`, and
`web/src/styles/theme.css`, written from `docs/v1/design/nocturne.css`
by `pnpm -C web gen:theme`. Both are gated, so an edit to one is a red
gate rather than a surprise later.

## Where to read

| If you are asking | Open |
|---|---|
| what is the stack, and what may I add to it? | `docs/v1/10-frontend.md` §Stack |
| how is the screen laid out? | `docs/v1/10-frontend.md` §Layout (from the mock) |
| where does a pane live, and how is one added? | `docs/v1/10-frontend.md` §Panes (cycle order) |
| how does the graph pane work? | `docs/v1/10-frontend.md` §Graph pane |
| what opens over the screen, and how does it close? | `docs/v1/10-frontend.md` §Overlays |
| what is bound to which key, and when is a binding live? | `docs/v1/10-frontend.md` §Keyboard |
| which event invalidates which query? | `docs/v1/10-frontend.md` §Realtime and caching |
| how does the SPA draw a plugin's panel? | `docs/v1/10-frontend.md` §Plugin renderers |
| what gets the operator's attention, and how? | `docs/v1/10-frontend.md` §Attention |
| what is the accessibility floor? | `docs/v1/10-frontend.md` §Accessibility and quality |
| how does auth work in the browser? | `docs/v1/10-frontend.md` §Auth in the browser |
| which token do I use for this colour or spacing? | `docs/v1/10-frontend.md` §Tokens → shadcn |
| what colour is a status? | `docs/v1/10-frontend.md` §Status colours |
| what may a call site write for a font size? | `docs/v1/21-design-refresh.md` §Type scale (normative) |
| what happens at a narrow viewport? | `docs/v1/21-design-refresh.md` §Narrow layout (normative) |
| how is the mock re-imported, and what may diverge from it? | `docs/v1/21-design-refresh.md` §Re-import (normative) |
| what must be green before this lands? | `docs/v1/21-design-refresh.md` §Gates (normative) |
| which commands run the SPA and its suites? | `AGENTS.md` §Commands |

## What to copy

- `web/src/panes/kinds/` — one file per renderer, which is where a new
  pane kind's neighbours live.
- `web/src/realtime/` — the SSE consumer and the invalidation map.
- `web/src/plugins/` — the manifest, the renderer registry and the
  bridge a custom element talks to.
- `web/src/keys/` — the keyboard map and its scoping.
- `web/e2e/` — the Playwright suite, which drives the built SPA against
  a real server with a fake agent behind it. It is the fastest way to
  see what a change is supposed to look like from outside.
- `docs/v1/design/` — the imported mock, which is the reference for
  layout and copy.

## Generated reference

This skill has no `reference/` directory of its own, deliberately. The
SPA's facts live in TypeScript, and a Python script restating them would
be exactly the second, weaker copy the whole design forbids. The two
things that *are* generated are already gated: `web/src/api/gen` and
`web/src/styles/theme.css`.

The event names the SPA subscribes to, with the payload each carries,
are `skills/athanore-workflows/reference/events.md`; the endpoints
behind the generated client are
`skills/athanore-api/reference/routes.md`.
