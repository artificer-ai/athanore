# T087 — SPA follows; end to end

**Task.** `docs/v1/17-serial-task-plan.md` § `### T087` (Do / Tests /
Done).
**Specs.** `docs/v1/22-live-registration.md` §SPA (normative), §Remove
(what a removed workflow's runs read), §Live mounting (the `?v=`
content version), §Testing (the SPA and Playwright bullets);
`docs/v1/10-frontend.md` §Realtime and caching (the table,
exact-before-glob, generated keys as prefixes), §Panes (the index
clamp), §Overlays (the library), §Plugin renderers (`CustomElementHost`
injects once), §Attention (the row's `⚠`, the precedent for a row
marker); `docs/v1/09-plugins.md` §Escape hatch (`?v=`, inject once,
never removed); `docs/v1/08-api.md` §Runs (`unregistered` on
`GET /api/runs`, computed per request); `docs/v1/13-testing.md`
§Pyramid and §Running examples on the fake; D49 (generated keys), D155
(keys as prefixes), D183 (the asset surface), D225 (never re-inject;
the notice), D236 (2) (the e2e prefix selector on `?v=`).

## Where the code is

Read before writing; every change below attaches to something that
exists.

- `web/src/realtime/invalidate.ts` — `queryKeys` (eight generated
  keys), `invalidations` (the table), `keysFor`, `Invalidator` with the
  250 ms coalescer. `web/src/realtime/sse.ts` already subscribes to
  `workflow.registered` / `workflow.replaced` / `workflow.unregistered`
  (T085 regenerated `EventName`; `EVENT_NAME_TABLE` carries them), so
  the frames arrive — nothing in the table catches them yet.
- `web/src/plugins/assets.ts` — `assetLoaded(url)` compares whole URLs
  against `script[data-athanore-asset]` in `document.head`;
  `injectAssets(urls)` injects what is not loaded; `injectedAssets()`.
  The document is the record; there is no module-level set (keep it
  that way).
- `web/src/panes/CustomElementHost.tsx` — the **only** caller of
  `injectAssets`, in a mount effect keyed on `[tag, workflow, assets,
  nothing]`, where `assets` is `useMemo(() => manifest.find(...)?.assets
  ?? [])`. A manifest refetch whose `?v=` moved produces a new array,
  re-runs the effect, rebuilds the element and — today — would inject the
  new URL, which `customElements.define` then throws on. That is the
  defect D225 names.
- `web/src/panes/manifest.ts` — `useManifestQuery`, `useManifestEntries`
  (read), `useManifest` (read + `usePanelRefreshRegistry`). Its header
  comment still says the manifest "only changes on restart"; that is
  false after T084 and is rewritten here.
- `web/src/panes/usePanes.ts` — reads `useManifest()`; the index clamp
  of 10 §Panes is `Math.min(index, panes.length - 1)` at read time, so a
  cycle that shrinks under `?pane=` already clamps. No change expected;
  a test proves it (below).
- `web/src/store/ui.ts` — the `useUi` zustand store; `feed` is the
  precedent for "the feed writes it, the banner reads it".
- `web/src/components/ServerDownBanner.tsx` — the strip under the
  header: `role="status"`, `data-testid`, the uppercase kicker, a
  bordered button. `web/src/App.tsx` renders it directly under `Header`.
- `web/src/components/RunList/RunList.tsx` — `Row` and `NarrowRow`;
  `Pending` draws `⚠` after the NODE cell with a `title`.
  `useRunList.ts`'s `RunRow` model carries `pendingRequests` off
  `RunSummary`; `RunSummary.unregistered?: boolean` is in
  `types.gen.ts` and **nothing in the SPA reads it** — no badge exists
  today.
- `web/src/overlays/Library.tsx` — `listWorkflowsApiWorkflowsGetOptions`
  for the list, `getSourceApiWorkflowsNameSourceGetOptions` per workflow
  (`useSources`); rows are `role="option"` with `data-workflow`; the
  viewer is `data-testid="library-source"`. `NewRun.tsx` reads the same
  list for its chip group (`radio` per workflow). `GraphCanvas.tsx`
  reads the source too. Nothing reads `getWorkflowApiWorkflowsNameGet`
  yet; its key is still invalidated because 22 §SPA names it.
- `web/e2e/support/server.ts` (`athanore serve` per test, `FakeACPAgent`
  via `ATHANORE_AGENT_COMMAND`, `ATHANORE_FAKE_SCENARIOS=web/e2e/
  scenarios`, one worker), `web/e2e/support/fixtures.ts` (`Dashboard`,
  where every locator of the suite lives), `web/e2e/plugin.spec.ts`
  (the `?v=`-tolerant script selector, the `plugin-element` test id).
- The fake: `athanore/testing/fake_acp.py` picks
  `<workflow>.<node>.json`, then `<node>.json`, then `default.json`;
  `default.json` is a text-only turn, so an agent node of any name with
  no scenario file of its own completes.

## What this task is

The dashboard reflects a registration the moment it happens, and is
honest about the one thing it cannot do. Then the whole feature is
proved end to end in CI on the fake agent.

### 1. Invalidation (`web/src/realtime/invalidate.ts`)

Add to `queryKeys`, each built by the generated `*QueryKey` helper:

- `workflows: () => listWorkflowsApiWorkflowsGetQueryKey()`;
- `workflow: () => withoutPath(getWorkflowApiWorkflowsNameGetQueryKey({ path: { name: '' } }))`;
- `source: () => withoutPath(getSourceApiWorkflowsNameSourceGetQueryKey({ path: { name: '' } }))`;
- `manifest: () => manifestApiPluginsGetQueryKey()`.

`withoutPath(key)` is a five-line helper in this file: the generated
key is `[{ _id, baseUrl, path }]` and the two name-keyed helpers type
`path` as required, so the prefix over **every** name is the generated
object with `path` taken off. TanStack's partial matching is deep over
objects, so `[{ _id, baseUrl }]` reaches `[{ _id, baseUrl, path: { name }
}]` for any name — the same prefix property D155 gives the run keys,
one parameter further up. This keeps `_id` and `baseUrl` generated
rather than hand-written (D49). **Decision to record**: a name-less
prefix is the generated key minus `path`, not a literal `_id`.

Add the row:

```ts
'workflow.*': () => [
  queryKeys.workflows(),
  queryKeys.workflow(),
  queryKeys.source(),
  queryKeys.manifest(),
  queryKeys.runs(),
],
```

Five keys, not four. 22 §SPA names the list, the single workflow, the
source and the manifest; `runs` is added here because `GET /api/runs`
answers `unregistered` per request from the live registry (08 §Runs)
and `remove` writes no run or task status and emits no `run.*`/`task.*`
(22 §Remove step 1, `Server.remove`) — a list refetched only on those
would show the marker of §3 when something unrelated moved, which is
exactly the D208 reasoning for `request.*`. The single-run key is not
reachable without a `run_id` and the overview does not draw the flag,
so it is not invalidated. **Decision to record**, and 22 §SPA's
sentence gains "and the run list" so 10 and 22 agree.

Coalescing is untouched: the three names go through `enqueue` like the
rest. The header comment of the table gains a paragraph on the row, in
the voice of the two that are there.

### 2. Stale assets (`web/src/plugins/assets.ts`, `panes/manifest.ts`, `store/ui.ts`)

`assets.ts`:

- `assetPath(url)`: the URL up to its first `?` — exported, because the
  banner and the tests want the same rule.
- `staleAssets(urls): string[]`: the URLs in `urls` whose path is
  already injected under a **different full URL** (read from
  `document.head` as `assetLoaded` reads, never from a set). Empty for a
  first injection (path absent), for an identical list (same full URL),
  and for a removal (nothing new listed).
- `injectAssets(urls)` skips a URL that is loaded **or stale**. D225
  says never; the host filters too (below), and the function is the
  last line of defence.

`store/ui.ts` gains, beside `feed`:

```ts
/** Workflow → the manifest URLs this document cannot follow (22 §SPA). */
staleAssets: Record<string, readonly string[]>
markStaleAssets: (workflow: string, urls: readonly string[]) => void
```

Merged in, never cleared: the document is what is stale, and only a
reload makes a new one. Documented in the store's header in the voice
of the `feed` paragraph. **Decision to record**: the flag lives in
`useUi`, keyed by workflow, and nothing unsets it.

`panes/manifest.ts` gains `useStaleAssets(manifest)`: an effect keyed on
the manifest that, for each entry, computes `staleAssets(entry.assets ??
[])` and calls `markStaleAssets(entry.workflow, stale)` when non-empty.
`useManifest()` calls it beside `usePanelRefreshRegistry`, so the check
runs **at manifest load** — where the pane host and the shell read the
manifest — and not only when a custom pane happens to mount: a pane
viewed earlier and cycled away from has its module in the document all
the same. Rewrite the file's header: the manifest changes on restart
*and on every `workflow.*`* (the invalidation row refetches it; the
`started_at` refetch in `sse.ts` stays for the restart case).

`panes/CustomElementHost.tsx`: key the mount effect on the assets'
**paths** (`assets.map(assetPath).join('\n')`) rather than the array,
holding the current list in a ref the way `latest` holds the scope, and
inject `injectAssets(latestAssets.current)`. A `?v=` bump then neither
re-injects nor rebuilds the element — "keeps rendering the old element
until then" (22 §SPA) — while a path added or removed still rebuilds it
as today. Update the component's comment ("Only the tag, the workflow or
the workflow's asset *paths* changing rebuilds it"). **Decision to
record.**

### 3. The notice and the marker (`components/`, `App.tsx`)

`web/src/components/PluginAssetsBanner.tsx`, the twin of
`ServerDownBanner`: reads `useUi(state => state.staleAssets)`; renders
`null` when empty; otherwise a `role="status"`
`data-testid="plugin-assets-banner"` strip with the same classes and
primitives — kicker `▲ plugin code changed`, the sentence `plugin code
changed — reload the page`, the workflow names (`Object.keys`, sorted,
as `<code>`), and a `reload` button. The button calls a `reload` prop
that defaults to `() => window.location.reload()`, so the unit test can
hand it a spy (jsdom's `location` is not spyable). It never dismisses;
the reload gives a document with nothing stale in it. `App.tsx` renders
`<PluginAssetsBanner />` directly under `<ServerDownBanner />` and its
header comment says so.

The run row's `unregistered` marker: `useRunList.ts`'s `RunRow` gains
`unregistered: boolean` (`run.unregistered === true`); `RunList.tsx`
gains `Unregistered`, the twin of `Pending`: after the WORKFLOW cell's
name, `⊘` with `title="this server has no workflow of that name"`,
`role="img"` and `aria-label="unregistered"`,
`data-testid="run-unregistered"`, in the muted colour — in `Row` and in
`NarrowRow`'s meta line. A glyph with a title rather than a word,
because the column is 104 px and `⚠` is the precedent; the `img` role
named by the word is what a glyph standing for one is to a screen
reader (`aria-label` on a bare `span` is a prohibited attribute to axe,
which the e2e gate below would refuse). **Decision
to record** (10 says nothing about drawing the flag; 22 §Remove says
the run "reads `running` and `unregistered: true`, which is the honest
report", and the SPA has to be able to show it).

### 4. End to end (`web/e2e/registration.spec.ts`, `support/fixtures.ts`)

Fixtures:

- A `scratch` fixture in `fixtures.ts`: `mkdtempSync(join(tmpdir(),
  'athanore-e2e-scratch-'))`, removed after the test. The workflow files
  a spec writes live here, outside the server's root.
- `Dashboard.submit` and `submitOverApi` take `workflow: string` (the
  `FixtureWorkflow` union stays for what it documents; a spec that
  registers its own workflow is not one of the six).
- `Dashboard` gains: `openLibrary()` (the header's `workflows` button;
  waits for `library`), `libraryRow(name)` (`[data-testid="library-list"]
  [data-workflow="<name>"]`), `librarySource()`, `closeOverlay()`
  (`esc`), `openNewRun()` / `newRunChip(name)` (the `radio` by name),
  `unregistered(title)` (`row(title).getByTestId('run-unregistered')`),
  `paneDot(name)` (`[data-pane="<name>"][role="radio"]`),
  `pluginAssetsBanner()`, `reloadFromBanner()` (clicks `reload` and
  waits for the shell as `open()` does).
- In the spec file, `api(server, method, path, body?)` over `fetch`,
  returning `{ status, json }`, and `writeWorkflow(scratch, source)`.

The spec's workflow file, written by the test (a `.py` under `scratch`,
stem `tempo_wf` — not a stdlib name, T085's lesson). Its shape:

```python
import asyncio
from pathlib import Path
from athanore import ACPAgent, Workflow

HOLD = Path("<scratch>/hold")          # the spec writes the absolute path in

class Builder(ACPAgent):
    pass                                # ATHANORE_AGENT_COMMAND puts the fake behind it

wf = Workflow("tempo")

@wf.node(start=True)
async def draft(linger):
    await Builder().run()               # default.json: a text turn, then end_turn
    return linger

@wf.node()
async def linger(finish):
    while HOLD.exists():                # the spec's gate: absent → straight through
        await asyncio.sleep(0.1)
    return finish

@wf.node()
async def finish():
    return "done"
```

The stall is a file the spec controls rather than a fake scenario:
recovery does not bump `attempt`, so a scenario that sleeps would sleep
again after the `POST` back and the run could never finish; a gate the
spec removes makes "the attempt stopped" and "the run resumed" two
observations of one node. **Decision to record.**

**Test 1 — `a workflow added, reloaded, removed and added back is
followed live`:**

1. `dashboard.open()`; write v1; `POST /api/workflows {target:
   "<file>:wf"}` → 201. Without touching the page: `openLibrary()` lists
   `tempo`; `closeOverlay()`; `submit('tempo', 'first light')` through
   the New Run overlay (the chip is offered); the row reaches
   `completed` within `RUN_TIMEOUT`; select it; `pane('graph')` shows
   `graphRow('draft')`, `graphRow('linger')`, `graphRow('finish')`.
2. Write v2 with `finish` renamed `publish`; `PUT /api/workflows/tempo
   {}` (target omitted: the recorded one is re-resolved, which is
   `athanore workflows reload <name>`'s shape) → 200. `openLibrary()`;
   `librarySource()` contains `publish`; close. `submit('tempo',
   'second light')` → `completed`; select; graph shows `publish` and
   not `finish`.
3. `writeFileSync(HOLD)`; `runId = submitOverApi('tempo', 'held
   light')`; wait for `status('held light')` = `running` and the row's
   NODE cell = `linger`. `GET /api/runs/{runId}` → the task in
   `in_progress` (`taskId`). `DELETE /api/workflows/tempo` → 200 and
   `task_ids` equals `[taskId]` — the wire's statement that the attempt
   was interrupted (the stats row and the subprocess are the engine
   tests' business, 22 §Testing). Then, with no reload:
   `unregistered('held light')` visible; `status` still `running`;
   `openLibrary()` → `libraryRow('tempo')` count 0 while the six
   fixture workflows are still listed; close; `openNewRun()` →
   `newRunChip('tempo')` count 0; close.
4. `rmSync(HOLD)`; `POST` the same target → 201. `unregistered('held
   light')` count 0; `status('held light')` = `completed` within
   `RUN_TIMEOUT` (recovery reset the row to `ready`, the node found no
   gate); `openLibrary()` lists `tempo` again.

**Test 2 — `a plugin whose JavaScript changed says so; nothing else
does`:**

1. Write v3: `Workflow("tempo", assets="./static")`, one node `play`
   returning at once, `wf.panel("Tempo", slot="run", kind="custom",
   element="e2e-tempo")`; write `<scratch>/static/tempo.js` defining
   `e2e-tempo` whose `connectedCallback` renders `<p
   data-testid="tempo-word">one</p>`. `POST`. `submitOverApi('tempo',
   'tempo one')`; `select`; `showPane('Tempo', 'tempo')`; `tempo-word`
   reads `one`; one `script[data-athanore-asset^="/plugins/tempo/static/
   tempo.js"]`; `pluginAssetsBanner()` count 0.
2. Rewrite `tempo.js` to render `two`; `PUT /api/workflows/tempo {}` →
   200. The banner becomes visible and names `tempo`; the script count
   is still 1 and its `data-athanore-asset` is the **old** URL; the
   element still reads `one`.
3. `reloadFromBanner()`; banner count 0; `select`/`showPane` again;
   `tempo-word` reads `two`; one script, and its URL differs from the
   one read in step 1.
4. `DELETE /api/workflows/tempo` → 200. `paneDot('Tempo')` count 0 (the
   cycle followed the manifest and the index clamped — the pane body
   shows a builtin); the banner stays absent.

Both tests put the page through the axe gate of `a11y.spec.ts` in the
state that shows the new surface — the `⊘` beside a `running` pill in
test 1 step 3, the banner in test 2 step 2 — under
`prefers-reduced-motion`, because a `running` pill pulses and axe reads
the quarter-opacity keyframe as a contrast failure of the pill, which
is the design's and is already answered by the media query
`theme.css` honours.

Both tests run in the suite's default configuration (`workers: 2`,
Chromium). `RUN_TIMEOUT` bounds every state wait.

### 5. Fold

- `docs/v1/10-frontend.md` §Realtime and caching: the table gains
  `"workflow.*": e => [["workflows"], ["workflow"], ["source"], ["plugins"], ["runs"]]`
  and a paragraph: what the refetch refreshes (library, chips, palette
  rows, pane cycle with its clamp), why `runs` is in the row, and the
  asset-version rule from 22 §SPA (inject a new workflow's assets as
  today; a URL whose path is injected under another `?v=` raises the
  persistent notice; never re-inject; a removed workflow's scripts stay
  loaded and inert). §Overlays, the library entry: replace "The mock's
  'hot-reloaded' claim is a later seam; v1 requires a restart." with
  "The list and the viewer follow `workflow.*` live (22 §SPA);
  registering from the overlay is a later seam." §Plugin renderers:
  "`CustomElementHost` injects manifest assets once — never a second
  version of one path (D225) — and mounts…". §Attention: two bullets —
  the `⊘` after the WORKFLOW cell for `unregistered`, and the
  `plugin-assets` strip beside the server-down banner.
- `docs/v1/22-live-registration.md` §SPA: "…the single-workflow and
  source queries, the manifest, and the run list — whose `unregistered`
  flag is computed per request (08 §Runs)". Nothing else in 22 moves.
- `docs/v1/15-decisions.md`: one row, D253, numbering the decisions
  marked above (`runs` in the row; the path-less prefix; the flag in
  `useUi`, never cleared; the check at manifest load; the host keyed on
  asset paths; the `⊘` marker; the spec-controlled stall gate and the
  axe check under reduced motion).
- `docs/v1/17-serial-task-plan.md` § T087: the `**Status.** Done.` line,
  in the same commit.
- `docs/site/src/guide/workflows.md`, the live-registration paragraph:
  one sentence — the dashboard follows all three without a reload, and
  when a plugin's JavaScript has changed under it, it says so with a
  reload notice rather than pretending. `guide/plugins.md` §The escape
  hatch: one sentence pointing at the same fact.

## What this task is not

- No control to register, reload or remove from the SPA; the library
  reflects registrations and does nothing to them (22 §Scope).
- No re-injection of any asset, ever (D225); no attempt to unload a
  removed workflow's module; nothing tears a pane down because its
  module is stale.
- No change under `athanore/`; `tests/snapshots/openapi.json` and
  `web/src/api/gen/` byte-identical (T085/T086 already carry the wire).
- No change to the pane cycle or the palette beyond what the refetch
  needs. If `usePanes` does not follow the manifest, that is a bug fixed
  in place, not a redesign.
- No `persist` in the e2e flow; the CLI tests own `--persist`.
- No overview-pane treatment of `unregistered`; the row is the surface.

## Tests

- **Vitest** `realtime/__tests__/invalidate.test.ts`: each of the three
  `workflow.*` names invalidates exactly the five keys and no run, task
  or stream key; `queryKeys.workflow()` / `source()` partially match a
  named key (`queryClient.getQueryCache().find` after `setQueryData`
  under the full generated key, or `invalidateQueries` marking it
  stale); coalescing holds across the three names in one window.
- `plugins/__tests__/assets.test.ts`: `staleAssets` is empty for a
  first injection, an identical list and a shorter list; names the URL
  whose path is present under another `?v=`; `injectAssets` of that
  list leaves the script count at one and the old URL in place.
- `panes/__tests__/manifest.test.tsx` (new): render a hook host under a
  `QueryClient` seeded at `manifestApiPluginsGetQueryKey()`; inject the
  entry's URL; `setQueryData` with `?v=` moved → `useUi.getState()
  .staleAssets` holds `{ gamedev: [newUrl] }`; a first load, an equal
  refetch and an entry removed leave it empty.
- `panes/__tests__/CustomElementHost.test.tsx`: a manifest refetch with
  a new `?v=` keeps the mounted element (same node identity) and injects
  nothing; a manifest that adds a path injects it.
- `panes/__tests__/usePanes.test.tsx`: `setQueryData` on the manifest
  key to a list without the run's workflow shortens the cycle and clamps
  the index that was on the dropped pane.
- `components/__tests__/PluginAssetsBanner.test.tsx`: nothing while the
  record is empty; the sentence, the workflow names and the button when
  it is not; the button calls `reload`; the store reset in `afterEach`
  as the server-down test resets `feed`.
- `components/RunList/__tests__/RunList.test.tsx`: `⊘` on a row whose
  summary carries `unregistered: true` and on no other, in both shapes.
- **Playwright** `registration.spec.ts`, the two tests of §4.

## Verification

```sh
pnpm -C web typecheck && pnpm -C web lint && pnpm -C web test
pnpm -C web build
pnpm -C web exec playwright test registration.spec.ts --workers=1
pnpm -C web exec playwright test plugin.spec.ts --workers=1   # the ?v= selector still holds
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
```

Then by hand against `./scripts/run.sh` with the SPA open: `athanore
workflows add examples/...:wf`, `reload`, `rm` from a second terminal
and watch the library, the chips, the run rows' `⊘` and the pane bar
follow without touching the page; edit a plugin's `.js`, `reload`, and
see the banner; press `reload` and see the new element.

## Done

- The SPA follows `workflow.*` without a page reload except when a
  plugin's JavaScript changed, and then says so with a working reload
  control; a run of a removed workflow is marked on its row; the
  end-to-end flow of 22 §Testing passes in CI on the fake; 10 and 22
  folded, 15 rowed, 17 marked; gate green; snapshot and generated client
  unchanged.
