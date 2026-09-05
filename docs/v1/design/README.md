# Design sources

Imported from the Claude Design project **Athanore Coding Agent Dashboard**
(`https://claude.ai/design/p/b7cb5192-4374-44e3-ae8f-2563907fa4ea`,
file `Athanore.dc.html`, design system "Nocturne") on 2026-09-05.

- `Athanore.dc.html` — the dashboard mock, verbatim. It is a
  `dc-runtime` template (`<x-dc>` markup with `{{ }}` bindings and a
  `DCLogic` component holding sample data). Read it as the reference for
  layout, spacing, copy, and interaction; do not run it as the app.
- `nocturne.css` — the Nocturne token sheet plus the application-level
  overrides the mock declares (mono type, 12px base, 2px radii, status
  colours, keyframes). `web/src/styles/theme.css` is generated from this.

The Nocturne readme's guidance that still applies to the app: outlined
primary actions (accent border, never a fill), accent as line and glow
rather than flood, contrast from the tonal ramps not saturation, no pure
black or white, `:focus-visible` as a 2px accent ring, disabled at 45 %
opacity, Phosphor icons where an icon is needed.

`10-frontend.md` §Design system is the normative spec derived from these
files; `15-decisions.md` records where the product deviates from the mock.
