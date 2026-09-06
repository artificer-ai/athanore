# T071 — Assets, `custom` panels, `window.athanore`

**Task.** `docs/v1/17-serial-task-plan.md` § `### T071`.
**Specs.** `docs/v1/09-plugins.md` §Assets and §Custom panels;
`docs/v1/12-security.md` §Plugins (the CSP these assets load under).

## What this task is

Third-party UI: a plugin ships a `.js`, the host mounts it as a custom
element, and `window.athanore` gives it exactly three capabilities —
fetch, subscribe, and the theme tokens.

## What this task is not

- **No arbitrary host access.** The surface is those three things. A
  plugin does not get the query client, the router or the store.
- No hard-coded pane knowledge in the host: the builtin elements
  (`ath-agent-stream`, `ath-requests`, `ath-run-graph`) resolve through
  the same registry, which is what proves the seam is real.
- Path traversal in an asset URL is a 404, not a file read.

## Steps

1. Server: resolve `assets` relative to the declaring module
   (`importlib.resources` when packaged), serve at
   `/plugins/{wf}/static/` via `StaticFiles`, and list
   `assets: [urls of *.js]` in the manifest.
2. SPA: `CustomElementHost` injects each asset **once** as
   `<script type="module">`, then renders
   `<element run-id task-id node>`.
3. `window.athanore = { fetch (bound to /api/plugins/{wf}/ with auth),
   subscribe(names, cb) (on the shared `EventFeed`), theme: {tokens} }`.
4. The builtin elements resolve to the SPA's own React components
   through the registry.

## Verification

Python:

- a missing assets directory fails **registration** (loudly, at startup,
  not on first request);
- a `../` traversal is 404.

Playwright: a test plugin element mounts and receives an event through
`subscribe`.

## Done

- Tests pass.
- `**Status.** Done.` on `### T071`, in the same commit.

## Files

```
athanore/plugins/mount.py
athanore/api/static.py
web/src/panes/CustomElementHost.tsx
web/src/plugins/registry.ts
tests/plugins/test_assets.py
web/e2e/plugin.spec.ts
docs/v1/17-serial-task-plan.md
```
