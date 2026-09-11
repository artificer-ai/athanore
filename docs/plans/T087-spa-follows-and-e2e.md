# T087 — SPA follows; end to end

**Task.** `docs/v1/17-serial-task-plan.md` § `### T087`.
**Specs.** `docs/v1/22-live-registration.md` §SPA, §Testing (the
Playwright flow); `docs/v1/10-frontend.md` §Realtime and caching (the
invalidation table, exact-before-glob, generated keys), §Panes (the
index clamp), §Overlays (the library), the server-down banner as the
precedent for a persistent notice; `docs/v1/09-plugins.md` §Escape
hatch (inject once, never removed); D49 (generated keys), D155 (keys
as prefixes), D183 (the asset surface), D225 (no re-injection; the
notice).

## What this task is

The dashboard reflects a registration the moment it happens, and is
honest about the one thing it cannot do. Then the whole feature is
proved end to end in CI on the fake agent.

### Invalidation (`web/src/realtime/invalidate.ts`)

1. A `workflow.*` row: invalidate `listWorkflowsApiWorkflowsGet`,
   `getWorkflowApiWorkflowsNameGet` (prefix — every name),
   `getSourceApiWorkflowsNameSourceGet` (prefix) and
   `manifestApiPluginsGet`, all through the generated `*QueryKey`
   helpers, added to `queryKeys` beside the eight there. Coalesced like
   the others. Nothing per-run is invalidated: a registration changes
   no run, and the run list already refreshes on its own events.
2. The `AthanoreEvent` union already carries the three new envelopes
   from T085's regenerated client; the row's type narrows on them.
   Whatever consumes the manifest to build the pane cycle (`panes/`,
   `useManifest`) and the palette's plugin rows refetches through the
   same query, so the cycle and the rows follow without new code — the
   pane index clamp of 10 §Panes handles a count that shrank. Confirm
   with a test rather than by reading.

### The changed-assets notice (`web/src/plugins/assets.ts`, the shell)

3. `injectAssets(urls)` gains a return value or a companion:
   `staleAssets(urls): string[]` — the URLs in `urls` whose **path**
   (URL without its query) is already injected under a **different
   full URL**. `assetLoaded` keeps comparing whole URLs, so a URL with
   a new `?v=` is "not loaded" and would be injected; the caller checks
   `staleAssets` first and injects only the URLs whose path is not
   injected at all. The record is the document (`data-athanore-asset`
   attributes), as it is today — no module-level set.
4. Where the manifest is consumed and assets injected (`plugins/
   index.ts` / `useManifest`), a stale list that is non-empty sets a
   piece of shell state; `App.tsx` renders a `PluginAssetsBanner` under
   the header beside `ServerDownBanner`, same primitives: `plugin code
   changed — reload the page` and a `reload` button calling
   `location.reload()`. It never dismisses on its own; it is gone after
   the reload because the document is new. It never appears for a
   first injection (path not present), an identical manifest (same full
   URL), or a removal (nothing new listed).
5. The old element keeps rendering until the reload — nothing tears a
   pane down because its module is stale.

### End to end (`web/e2e/registration.spec.ts`)

6. The suite's `athanore serve` per test (T068a) runs `FakeACPAgent`
   behind every agent. The spec writes a workflow file into the test's
   own tmp dir — one agent node whose fake scenario submits and
   completes — and drives the operator API and the SPA together:
   - `POST /api/workflows` with the file target; the library overlay
     lists it and the new-run chips offer it; start a run through the
     UI; it completes.
   - Rewrite the file renaming the node; `PUT /api/workflows/{name}`;
     the library's source view shows the new text; start a run; the
     graph pane shows the new node's name.
   - Start a run whose fake scenario stalls mid-turn; `DELETE` while it
     is `in_progress`; the run row shows the `unregistered` treatment
     the run list already has for that flag and the attempt's transcript
     stops growing; the library no longer lists the workflow.
   - `POST` it back; the run resumes and completes.
   - A variant with a `custom` panel and an asset: after `PUT` with a
     changed `.js`, the banner is visible and the old panel still
     renders; after `page.reload()` the banner is gone and the new
     element renders.
7. **Fold into 10.** §Realtime and caching gains the `workflow.*` row
   in its table and the asset-version paragraph; §Overlays' library
   entry says it reflects registrations live; the banner is listed
   beside the server-down banner.

## What this task is not

- No control to register, reload or remove from the SPA. The library
  shows `target` if it is cheap to show and nothing more; a button is
  a later seam (22 §Scope).
- No re-injection of any asset, ever (D225); no attempt to unload a
  removed workflow's module.
- No change under `athanore/`; snapshot untouched.
- No change to the pane-cycle or palette code beyond what the refetch
  needs — if the cycle does not follow the manifest today, that is a
  bug to fix in place, not a redesign.

## Tests

- **Vitest** `realtime/__tests__/invalidate.test.ts`: each of the three
  events invalidates exactly the four keys and no run key; coalescing
  holds. `plugins/__tests__/assets.test.ts`: `staleAssets` is empty for
  a first injection, for an identical list, for a removal (a shorter
  list), and names the URL whose path is present under another `?v=`;
  the stale URL is not injected. Shell: the banner renders when the
  state is set and its button calls `location.reload` (spy);
  `useManifest`/panes: a manifest refetch that drops a workflow
  shortens the cycle and clamps the index (drive the query cache).
- **Playwright** `registration.spec.ts` per step 6, in the default
  worker configuration the other specs use.

## Verification

```sh
pnpm -C web typecheck && pnpm -C web lint && pnpm -C web test
pnpm -C web exec playwright test registration.spec.ts --workers=1
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
```

Then by hand against `./scripts/run.sh` with the SPA open: `athanore
workflows add`, `reload`, `rm` from a second terminal and watch the
library, the chips and the pane bar follow without touching the page;
edit a plugin's `.js`, `reload`, and see the banner.

## Done

- The SPA follows `workflow.*` without a page reload except when a
  plugin's JavaScript changed, and then says so with a working reload
  control; the end-to-end flow of 22 §Testing passes in CI on the fake;
  10 folded; gate green; snapshot unchanged.
