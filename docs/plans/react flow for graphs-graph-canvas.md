# react flow for graphs — the graph pane becomes a React Flow canvas

**Task.** Not a `Txxx` row: this is operator-requested work arriving
through the `feature` workflow, after the v1 build order. Nothing in
`docs/v1/17-serial-task-plan.md` changes and no `**Status.** Done.` line
is added — this file is the scope fence instead.

**Specs.** `docs/v1/10-frontend.md` §Stack (the row that says React Flow
is *not* used, which this change reverses), §Panes item 5, §Graph pane
(the normative description of the renderer), §Status colours,
§Accessibility and quality (colour is never the only signal; the axe
floor), §Realtime and caching (which cache entry the pane reads);
`docs/v1/08-api.md` §Runs and §Graph semantics (`GET
/api/runs/{id}/graph` — `nodes` in generation order and within a
generation in declaration order, `state` precedence, `branches`,
`arrivals`, `edges` with `kind` and `traversed`, the 404
`unknown_workflow`); `docs/v1/02-architecture.md` §Library choices (the
Frontend row); `docs/v1/12-security.md` §Plugins (the CSP the built SPA
is served under); `docs/v1/21-design-refresh.md` §Type scale (D195:
**what scales is type, not density**) and §Narrow layout (D194, the one
`md` breakpoint); `docs/v1/13-testing.md` §Pyramid; D32 (the rail, which
this supersedes), D131 (the graph route's nine choices), D167 (the six
the rail decided — four of them survive), D178/D179 (the axe floor and
what 10 already lags).

## What this change is

`web/src/panes/kinds/GraphRail.tsx` is deleted and replaced by
`web/src/panes/kinds/GraphCanvas.tsx`, which draws the same data — the
same three queries, the same header bar, the same aside — as a **React
Flow canvas**: one node per workflow node, laid out in ranks by the
`generation` the route already sends, with the graph's edges drawn as
edges rather than as `▼` connectors and a right-hand rail of 1 px spans.

Everything the brief fences stays: the `WORKFLOW GRAPH · <workflow>`
header and its three legend dots, the EDGES block, the SOURCE path and
`open definition`, the click-to-filter-the-log interaction, the
right-click menu with its two operations and its printed refusal, and
`GET /api/runs/{id}/graph` itself — **no wire change, no OpenAPI
regeneration, no `web/src/api/gen` churn.**

D32 said the pane is the mock's rail list and not a React Flow canvas.
The operator has ruled otherwise; D32 is marked superseded and 10
§Stack and §Graph pane are rewritten, rather than left standing while
the tree contradicts them (the drift D179 exists to stop).

### The six questions the brief left open, settled

1. **One flat graph. A fan-out does not duplicate a node** — it draws
   branch chips inside the one node it fanned. The forcing argument is
   the wire: `edges` name *nodes*, not attempts (08 §Graph semantics), so
   a renderer that drew `render` three times would have to invent which
   of the three each arrow into and out of `render` connects. That is
   exactly the invention 01 §Real data only forbids, and it is why the
   rail could get away with sub-lists (a list has no arrows) and a canvas
   cannot. What the sub-lists carried instead of being duplicated: a
   `graph-branch` chip per branch, keyed and labelled by D167 (1)'s
   frame stack and coloured by D167 (2)'s per-branch state.
2. **A back edge leaves and arrives on the node's right-hand side**, as
   a `smoothstep` that bows out to the right, and it is the only edge
   kind that carries a `loop` label. That keeps the mock's right-hand
   rail idiom — a loop is the thing drawn down the right — without
   asking the operator to read a colour. Forward and join edges go
   bottom-to-top down the ranks. `join` edges are drawn exactly as
   forward edges: the `⋈` glyph on the target is what says a node is a
   fan-in (D167 (4)), and the EDGES aside lists the arrows by kind
   already, so a third geometry would be a third notation for a fact
   already stated twice.
3. **Fixed layout by generation. No Dagre, no ELK.** `y` is the node's
   rank among the distinct generations present; `x` spreads the nodes
   of one rank left to right in the order the route sent them, centred
   on the rank. Both halves are facts already on the wire (08: "nodes
   come out in generation order and, within a generation, in declaration
   order", D131 (6)), and a layout engine would spend a dependency and
   an async measurement pass to *re-derive* the first and *reorder* the
   second — reordering a rank to reduce crossings would hide the
   author's declaration order, which D131 (6) kept deliberately. The
   layout is a pure function in `graph.ts`, tested without a DOM.
   Crossings are not minimised, and the plan says so rather than
   pretending otherwise.
4. **The detail column goes inside the node**, on a second line, keeping
   `data-testid="graph-detail"` and D167 (3)'s precedence unchanged. Not
   a tooltip: `attempt 2 · 105s` ticks once a second and `2 of 3
   arrived` is the one thing an operator watching a fan-in is waiting
   for — putting live facts behind a hover hides them, and hides them
   completely below the breakpoint, where there is no hover (21 §Narrow
   layout).
5. **Fit to view once per run; zoom by button, pan by drag, and the
   wheel belongs to the pane.** `fitView` on mount, remounted per `runId`
   so switching runs refits and a run whose graph is being watched is
   never yanked out from under a manual pan. `zoomOnScroll={false}` and
   `preventScrolling={false}`, so a wheel over the canvas scrolls the
   pane as it does everywhere else in the app; `<Controls>` carries zoom
   in / out / fit as real buttons. Below the breakpoint the canvas is a
   fitted picture: no pan, no zoom, no controls, and the EDGES list
   underneath carries the detail. Nodes are **not** draggable — the
   layout is derived from the response, so a dragged node would snap
   back on the next `run.*` invalidation.
6. **`graph.ts` keeps its unit suite and grows a layout suite; the
   component suite is rewritten, not ported.** The layout, the branch
   grouping, the detail column and the legend are pure functions and
   that is the lowest layer that can express them (13 §Pyramid). The
   component test keeps its fixtures and its seeded-cache harness and
   asserts on what the canvas puts in the DOM. The Playwright specs
   mostly do not move at all, because the node card keeps
   `data-testid="graph-row"`, `data-node` and `data-state` — see
   §Tests.

## The dependency

**`@xyflow/react`, not `react-flow-renderer`.** The brief names
`react-flow-renderer`; that package is deprecated on npm ("renamed to
`reactflow`"), was last published as v10, and `reactflow` in turn became
`@xyflow/react` at v12. The boring choice is the maintained name:
`@xyflow/react` `^12.11.6`, MIT, peer-depends `react >=17`.

Three things about it that this plan is built on, each verified against
the published bundle rather than assumed:

- **A node with an explicit `width` and `height` is "measured" already**
  (`nodeHasDimensions` reads `measured ?? width ?? initialWidth`). Every
  node this pane makes carries both, from the layout function, so React
  Flow never needs a measurement round trip: the canvas is deterministic,
  it draws the same picture on the first frame as on the second, and it
  renders in jsdom, where nothing has a size.
- **It brings its own `zustand` 4** as a dependency, beside the app's 5.
  Accepted: pnpm's isolated store keeps them apart, and the second copy
  is a few kilobytes against a library that would otherwise have to be
  hand-written.
- **The attribution link stays.** `proOptions.hideAttribution` is the
  subscriber's switch and this project is not one, so the `React Flow`
  link keeps its corner. It is restyled for contrast (below), not
  removed.

`pnpm -C web add @xyflow/react` — and **commit `pnpm-lock.yaml`, which
is at the repository root and not under `web/`, with `web/package.json`**:
`./scripts/test.sh` installs `--frozen-lockfile`, so a lockfile left
behind fails the gate before a single test runs.

## Files and what each does

### 1. `web/src/panes/kinds/graph.ts` — the shape, now with positions

Kept, unchanged in behaviour: `GLYPHS`, `nodeGlyph`, `nodeDetail` (and
its `attemptsOf` / `spentText` / `runningText` helpers), `branchState`,
`STATE_RANK`, `branchLabel`, `branchTag`, `BranchKey`,
`BRANCH_KEY_CHARS`, `framesOf`, `LegendKind`, `LegendRow`,
`LEGEND_GLOSS`, `legendRows`, `moveRefusal`. Those are D167 (1)–(5) and
they are as true of a canvas as of a list.

Deleted with the rail: `RailRow`, `Rail`, `railRows`, `withLoops`,
`noRail`, `group`, `Group`, `Block`, `closedByJoin`. Nothing else
imports them.

New, and this is the substance of the change:

```ts
/** The card one node draws, and what the canvas needs to place it. */
export type NodeCard = {
  node: GraphNode
  state: NodeState        // node.state; the wire's own word
  glyph: string
  tone: StatusTone
  detail: string
  branches: BranchChip[]  // the fan-outs this node ran in, or []
}

/** One branch of one fan-out, as a chip inside the node. */
export type BranchChip = {
  tag: string             // branchTag(branch) — the data- attribute
  label: string           // branchLabel(branch) — the chip's title
  short: string           // `2/3`, or `#2` on the fallback
  state: NodeState        // branchState(this branch's attempts)
  tone: StatusTone
}

export type GraphFlowNode = Node<NodeCard, 'athanore'>
export type GraphFlowEdge = Edge

export function graphLayout(
  graph: GraphOut | undefined,
  tasks: readonly TaskView[] | undefined,
  now: number,
): { nodes: GraphFlowNode[]; edges: GraphFlowEdge[] }
```

`Node` and `Edge` are imported `import type` from `@xyflow/react`; the
module still exports no component, so React Fast Refresh and
`react/only-export-components` are satisfied exactly as the docblock
already explains.

**The branches of one node** replace `group()`. For each node, take
`branches` entries with a non-null `from_task` (a join takes none — a
join is where branches stop being separate, and it is drawn once), key
each by `framesOf(entry, byId)` with the entry's ordinal within that
fan-out as the fallback, sort the resulting list by `(fromTask, index ??
ordinal)` — the surviving half of `ordered()` — and make one
`BranchChip` per entry. `short` is `${index+1}/${count}` when the frames
said, `#${ordinal+1}` when they did not, which is the same "say only
what the wire said" rule `branchLabel` already follows. A node whose one
branch has `from_task: null` gets `branches: []` and no chip row.

**The layout constants**, absolute pixels, because D195 says what scales
is type and not density:

```ts
const NODE_WIDTH = 208
const NODE_HEIGHT = 56          // glyph + name, then the detail line
const BRANCH_ROW = 18           // added when the node draws chips
const COLUMN_GAP = 32
const RANK_GAP = 56
```

**The placement**, and it is the whole algorithm:

- Bucket the nodes by `generation`, preserving the route's order within
  a bucket. Sort the distinct generations ascending; a node's **rank** is
  its generation's index in that list, so a workflow whose generations
  are not contiguous leaves no empty band.
- A rank's height is the tallest card in it. `y` of a rank is the
  running sum of the previous ranks' heights plus `RANK_GAP` each.
- `x` of the `i`th of `n` cards in a rank is
  `(i - (n - 1) / 2) * (NODE_WIDTH + COLUMN_GAP)`, so a linear workflow
  is a straight column and a fan-out spreads symmetrically about it.

**The edges.** One React Flow edge per `GraphEdge`, `id`
`${kind}:${from}→${to}`, skipping any edge whose ends are not both in
the node set (the same defensive rule `withLoops` had). For `back`:
`sourceHandle: 'right-source'`, `targetHandle: 'right-target'`, `type:
'smoothstep'`, `pathOptions: { borderRadius: 12, offset: 24 }`,
`label: 'loop'` (plus ` ×n` when `traversed > 1`), `zIndex: 0`. For
`forward` and `join`: `sourceHandle: 'bottom'`, `targetHandle: 'top'`,
`type: 'smoothstep'`, `label` only when `traversed > 1`. Every edge
carries `markerEnd: { type: MarkerType.ArrowClosed }` and
`data: { kind, traversed }`; an edge with `traversed === 0` is dashed
and drawn in neutral-800, an edge this run took is solid neutral-700.
That is one rule with two facts in it — geometry says which kind of
arrow, weight says whether this run took it — and it is what replaces
the rail's `◀`/`loop` vocabulary.

### 2. `web/src/panes/kinds/GraphCanvas.tsx` — the renderer

New file; `GraphRail.tsx` is deleted. Its docblock is rewritten from the
old one: keep the three paragraphs that are still true (the three
requests and *why each is the app's own cache entry*; clicking is the
log and right-clicking is the two node operations; the shape is
`./graph.ts`) and replace the two that are not (the rail description and
the "no graph library and no canvas" paragraph, which now says the
opposite and cites this plan and D206).

Unchanged and moved across verbatim: `useGraph`, `useSource`, `Bar`,
`LegendDot`, `Menu`, `NodeMenu`, `Aside`, `Status`, the `rerun` / `move`
mutations with `refresh()` and the `notice` line, `focusedTask`, the
header bar, the four placeholder / error / loading branches, and the
component's four props (`runId`, `taskId`, `onOpenNode`,
`onOpenLibrary`). Deleted: `INDENT_PX`, `Connector`, `LoopRail`,
`BranchLabel`, `Row`.

New, in the same file (so it exports components only):

```tsx
const NODE_TYPES = { athanore: GraphNodeCard } as const
```

Module scope, not built in render — React Flow warns (and re-mounts
every node) when `nodeTypes` changes identity.

**`GraphNodeCard`** is `memo(function GraphNodeCard({ data }: NodeProps<GraphFlowNode>))`:

- Four `<Handle>`s, all `isConnectable={false}` and `aria-hidden`:
  `type="target" position={Position.Top} id="top"`,
  `type="source" position={Position.Bottom} id="bottom"`, and the pair
  `id="right-source"` / `id="right-target"` both at `Position.Right`.
  They are styled to 1 px and transparent — the graph is not editable,
  so a handle is an anchor point and nothing an operator should see.
- A `<button type="button">` filling the card, carrying
  `data-testid="graph-row"`, `data-node`, `data-state` and, when it has
  chips, `data-branches={n}`. **The test ids keep the rail's names on
  purpose**: `web/e2e/support/fixtures.ts`, `run.spec.ts`, `a11y.spec.ts`
  and `App.test.tsx` all reach for `graph-row` / `graph-detail`, and
  renaming a hook that still means the same thing would churn four files
  for a word.
- Inside: the glyph (`aria-hidden`, `toneClass(tone)`,
  `tonePulses(tone) && 'animate-ath-pulse'`), the name (`truncate`), and
  the detail line (`data-testid="graph-detail"`, `text-hint`, `truncate`)
  when it is non-empty — the same three things the row drew, stacked
  rather than in a line.
- The chip row when `branches.length > 0`: one
  `<span data-testid="graph-branch" data-branch={tag} data-state={state}
  title={label}>` per chip, drawing `short` in `toneClass(tone)`. The
  chips are the only place a branch is named now, and their `title` is
  `branchLabel`'s full `branch 2 of 3 · beta · from task 26`.
- The card's border and background are the rail row's, unchanged: the
  accent pair while `state === 'in_progress'`, neutral-800 on `bg-card`
  otherwise, `hover:border-[var(--color-accent-500)]`.

**The canvas**, in place of the rail column:

```tsx
<ReactFlow
  key={runId}
  nodes={layout.nodes}
  edges={layout.edges}
  nodeTypes={NODE_TYPES}
  colorMode="dark"
  fitView
  fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
  minZoom={0.4}
  maxZoom={1.6}
  nodesDraggable={false}
  nodesConnectable={false}
  nodesFocusable={false}
  edgesFocusable={false}
  elementsSelectable={false}
  zoomOnScroll={false}
  zoomOnDoubleClick={false}
  preventScrolling={false}
  panOnDrag={!narrow}
  zoomOnPinch={!narrow}
  aria-label={`workflow graph${workflow === undefined ? '' : ` for ${workflow}`}`}
  onNodeClick={(_, node) => { onOpenNode?.(node.id) }}
  onNodeContextMenu={(event, node) => {
    event.preventDefault()
    openMenu(node.data.node, event.clientX, event.clientY)
  }}
  onPaneClick={() => { setMenu(null) }}
>
  {!narrow && <Controls showInteractive={false} position="bottom-left" />}
</ReactFlow>
```

`narrow` is `useIsNarrow()` (`web/src/lib/useIsNarrow.ts`). No
`<Background>` and no `<MiniMap>`: the mock has neither, and the pane's
own surface is the background.

`nodesFocusable={false}` is load-bearing for the keyboard and for axe:
React Flow's node wrapper takes `tabIndex={0}` and `role="group"` only
when nodes are focusable, and the card's own `<button>` is already the
tab stop and already the thing `⏎` activates. One tab stop per node, and
the click handler fires for a keyboard `⏎` because the button's click
bubbles to the wrapper React Flow listens on.

**The body layout** replaces the wrapping flex row:

```tsx
<div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
  <div className="h-[320px] flex-none md:h-auto md:min-h-0 md:min-w-0 md:flex-1">
    …ReactFlow…
  </div>
  <Aside … />   {/* md:w-[300px] md:flex-none md:overflow-y-auto md:border-l */}
</div>
```

At `md` and above the canvas fills the pane and the aside scrolls
beside it in a fixed 300 px column; below it the canvas is a 320 px
fitted picture with the aside flowing underneath and the pane scrolling
as one. `Aside`'s own markup, copy and classes are untouched (brief, out
of scope) except for the wrapper classes that place it, which the rail
owned rather than the aside.

The `notice` line moves to just under the header bar, `flex-none`, so an
action's result is not inside a canvas that can be panned away from it.

### 3. `web/src/styles/reactflow.css` (new) and `web/src/index.css`

`index.css` gains two lines after the theme import, and a sentence in
its header comment saying what they are:

```css
@import "@xyflow/react/dist/style.css";
@import "./styles/reactflow.css";
```

`styles/reactflow.css` is hand-written (unlike its neighbour
`theme.css`, which is generated — say so in its header) and does exactly
one thing: map React Flow's `--xy-*` variables onto Nocturne tokens,
scoped to `.react-flow`, so nothing in the pane is a hex and nothing
needs `!important`:

- `--xy-edge-stroke`, `--xy-edge-stroke-width`, `--xy-edge-label-color`,
  `--xy-edge-label-background-color`;
- the `--xy-controls-button-*` set and `--xy-controls-box-shadow`, onto
  `--color-surface` / `--color-neutral-800` / `--color-neutral-300`;
- `--xy-attribution-background-color: transparent`, and
  `.react-flow__attribution a { color: var(--color-neutral-400) }` — the
  stylesheet hard-codes `#999` on a translucent grey, which composites
  to roughly 3.2:1 on Nocturne's background and would be a *serious*
  axe contrast violation on a page the gate runs axe over
  (`web/e2e/a11y.spec.ts`, D178). This is the one rule in the file that
  is a fix rather than a mapping, and the a11y spec is what proves it.

The SPA is served under `style-src 'self' 'unsafe-inline'`
(`athanore/api/static.py`, 12 §Security), which the canvas needs and
already has: React Flow positions every node and the viewport with an
inline `transform`, exactly as `react-resizable-panels` already does.

### 4. `web/src/panes/kinds/index.ts` and `web/src/plugins/registry.ts`

`export { GraphRail } from './GraphRail'` becomes
`export { GraphCanvas } from './GraphCanvas'`; the registry's import and
its `createElement(GraphRail, …)` follow, with the same four props. The
comment above `registerElement('ath-run-graph', …)` says "The rail list
of 10 §Graph pane" — rewrite it to name the canvas; the second sentence,
about the EDGES column being part of the pane's body rather than a
section poured into the host's scroller, is still exactly why
`scrolls: true`, and stays.

### 5. `web/src/test-setup.ts` — two more shims

In the file's established voice (each shim says what jsdom lacks, who
reaches for it, and what the stub tells the truth about):

- `window.DOMMatrixReadOnly`: React Flow's `updateNodeInternals` reads
  the viewport's computed `transform` through one. A stub that parses
  nothing and reports `m22 = 1` is the truth of the environment — jsdom
  computes no transform, so the zoom is 1.
- `SVGElement.prototype.getBBox`: React Flow's edge labels measure
  themselves to centre their background. Returning a zero box is the
  truth of an engine that performs no layout; the label is still in the
  DOM, which is what a test asserts on.

Both are `??=`, both are global, and neither changes an existing test:
`ResizeObserver` keeps the inert implementation it has, because every
node this pane makes carries an explicit `width` and `height` and never
waits to be measured.

## Documents

- **`docs/v1/10-frontend.md` §Stack.** Replace the paragraph under the
  table ("React Flow is **not** used…") with the opposite: the graph
  pane is a React Flow canvas (`@xyflow/react`), laid out from the
  `generation` the graph route sends, and the rail list it replaces is
  D32, superseded by D206. Add a Graph row to the table:
  `@xyflow/react` — "The graph pane's canvas; nodes carry explicit
  dimensions and a layout computed from `generation`, so no measurement
  pass and no layout engine".
- **`docs/v1/10-frontend.md` §Graph pane.** Rewritten. The header bar,
  the legend, the EDGES block, the SOURCE path, `open definition`, the
  click-to-log and the right-click menu keep their sentences word for
  word. What changes: one node per workflow node with its glyph, name
  and detail line; ranks by generation, declaration order across a rank,
  centred; forward and join edges down the ranks, back edges bowing out
  to the right with a `loop` label; an untaken edge dashed and a
  repeatedly taken one labelled `×n`; a fan-out drawn as branch chips
  inside the node rather than as sub-lists, each chip carrying that
  branch's own state; fit-to-view on load, buttons for zoom, drag to
  pan, wheel belongs to the pane, nodes not draggable; below the
  breakpoint a fitted picture with the EDGES block underneath.
- **`docs/v1/10-frontend.md` §Panes item 5** keeps its one line; it
  already only says "See §Graph pane".
- **`docs/v1/02-architecture.md` §Library choices.** The Frontend row
  gains `@xyflow/react` (React Flow) beside the other named libraries.
- **`docs/v1/15-decisions.md`.** D32's Status becomes
  `superseded by D206`; its Decision and Reason text is left as the
  record of what was decided in 2026-09. One new row, **D206**, dated
  2026-09-10, marked `**new**`, covering: (1) the graph pane is a React
  Flow canvas (`@xyflow/react`, not the deprecated
  `react-flow-renderer`), superseding D32; (2) **one node per workflow
  node** — a fan-out draws branch chips and never duplicates a node,
  because `edges` name nodes and a duplicate would force the renderer to
  invent which copy an arrow connects; D167 (1) and (2) survive as the
  chips' key and colour; (3) **layout is a pure function of
  `generation`** — ranks down, declaration order across, centred, fixed
  pixel constants — and no Dagre or ELK, because both halves are already
  on the wire (D131 (6)) and a layout engine would reorder the half that
  was deliberate; crossings are not minimised; (4) **every node carries
  an explicit `width`/`height`**, so React Flow needs no measurement
  pass, draws the same picture on the first frame, and renders in jsdom;
  (5) **back edges bow out to the right and are the only labelled kind**
  (`loop`), join edges are drawn as forward edges because the `⋈` glyph
  and the EDGES aside already name them, and an edge with `traversed ===
  0` is dashed; (6) **the detail column is inside the node, not a
  tooltip**, because it ticks and because there is no hover below the
  breakpoint; (7) **fit on load, zoom by button, pan by drag, wheel to
  the pane, no dragging nodes**, and below the breakpoint a fitted
  picture with no pan or zoom; (8) the React Flow attribution stays and
  is restyled for contrast rather than hidden, `hideAttribution` being
  the subscriber's switch; (9) the node card keeps `graph-row` /
  `graph-detail` as its test ids so the e2e fixtures carry over.
- **Not** updated: `docs/v1/17-serial-task-plan.md` § T063e and
  `docs/plans/T063e-graph-rail-renderer.md` describe the rail. They are
  the record of what that task shipped; 10 §Graph pane is the document
  that specifies the behaviour. `docs/v1/14-migration-and-phasing.md`'s
  risk row ("The rail-list graph has no design for fan-out") is likewise
  a phase-4 record and stays.

## Tests

**`web/src/panes/__tests__/fixtures.ts`** keeps `LINEAR_GRAPH`,
`FANOUT_GRAPH`, `JOINED_GRAPH`, `GRAPH_RUN`, `WORKFLOW_SOURCE`,
`graphNode`, `linearRun`, `fannedRun` as they are — they are the three
shapes a run can have and they are all still needed. Add one graph whose
generations are not contiguous only if a rank test needs it; otherwise
nothing here changes.

**`web/src/panes/__tests__/GraphCanvas.test.tsx`** (renamed from
`GraphRail.test.tsx`, keeping the `draw()` harness, the seeded query
client, `NOW`, `stubFetch` and the fake timers). The describes that
survive nearly intact, because they test `graph.ts` directly and not the
DOM: the detail column (all six of D167 (3)'s forms), the EDGES block,
`branchState`, `moveRefusal`. The describes that are rewritten:

- **`graphLayout` — the ranks.** A linear graph puts every node at the
  same `x` and in ascending `y`; two nodes of one generation are a rank,
  centred, `NODE_WIDTH + COLUMN_GAP` apart, in the route's order; a
  workflow whose generations skip a number leaves no empty band; every
  node carries `width` and `height`, and a node with chips is
  `BRANCH_ROW` taller.
- **`graphLayout` — the edges.** A forward edge is bottom→top; a back
  edge is right→right and carries `loop`; a join edge is drawn as a
  forward edge; `traversed > 1` adds `×n` and `traversed === 0` marks
  the edge untaken; an edge naming a node the graph does not have is
  dropped.
- **the branch chips.** Two branches of one fan-out are two chips on one
  node and the node is drawn once (the rail's "`render` appears twice"
  assertion, inverted — this is the test that proves question 1 was
  answered); the chips are keyed by the attempts' frames and not by
  `from_task` (the D167 (1) case, with the two branches finishing out of
  order); each chip carries its own branch's state while the node
  carries the node's; a node reached by a single path draws none; a join
  draws none.
- **the node card.** Glyph per state, `⋈` on a join in every state,
  the pulse on the node in progress and nothing else, the detail line
  present or absent, `data-node` / `data-state` present.
- **clicking and the menu.** Unchanged in intent: a click calls
  `onOpenNode` with the node's name; a right-click opens the menu on the
  node it was opened on; move is disabled on a join with its refusal
  printed; `esc` closes; the rerun and the move post and report; a
  refused action says what it said. These now go through React Flow's
  `onNodeClick` / `onNodeContextMenu`, so they are worth keeping as
  component tests rather than moving down.
- **the states with no graph.** Unchanged: no run selected, 404
  `unknown_workflow`, loading, no SOURCE line.

**`web/src/App.test.tsx`** — the two `findByTestId('graph-row')` clicks
keep working unchanged. Read the surrounding docblock at line ~906,
which names `GraphRail.test.tsx`, and update the file name it cites.

**`web/e2e/support/fixtures.ts`** — `graphRow` and `graphDetail` keep
their selectors. Add `graphBranches(node)` returning the chips of one
node.

**`web/e2e/run.spec.ts`, `web/e2e/a11y.spec.ts`** — untouched. They
assert `data-state` on `graphRow(...)` and visibility, and both hold: a
node with explicit dimensions is `visible` in a real browser, and the
a11y gate is what proves the attribution and the controls are legible.
If either moves, it is because the gate found something, and the fix
belongs in `styles/reactflow.css`, not in the assertion.

**`web/e2e/fanout.spec.ts`** — the one spec that must change. Keep
`graphDetail('release')` reading `1 of 2 arrived` and then losing it
(that is `arrivals`, and it is unaffected). Replace the
`graph-branch-label` assertions: expect `graphBranches('render')` to
have two chips, with distinct `data-branch` values, at least one of them
in a different `data-state` from the other while the fan-out is
mid-flight — which is the same fact the two sub-lists proved, stated on
the shape that replaced them.

**`web/e2e/mobile.spec.ts`** — one new test: below the breakpoint the
graph pane draws its nodes and the EDGES block underneath, and the
canvas shows no zoom controls.

Coverage stays at the 80 % gate on all four metrics
(`web/vite.config.ts`), and `styles/reactflow.css` is CSS, so nothing
about the threshold changes.

## Verification

```sh
./scripts/test.sh
git diff --exit-code tests/snapshots web/src/api/gen
pnpm -C web exec playwright test run.spec.ts fanout.spec.ts a11y.spec.ts mobile.spec.ts --workers=1
```

Then by hand, `./scripts/run.sh`: submit a `feature_build` run and a
`gamedev` run (the two fan-out examples 14 names) and watch the canvas
while they move — the node in progress pulses, a branch chip changes
colour before its node does, the join counts arrivals and then stops.
Follow a loop-back on the `probe` workflow and check the right-hand bow
and its `loop` label. Zoom out with the controls, pan, then switch runs
and confirm the next graph is fitted rather than left at the last pan.
Check the whole pane at `small` and at `xlarge` — the cards are fixed
pixels and the type is not, which is D195's rule and the thing most
likely to look wrong. Drag the window under 768 px and confirm the
canvas becomes a fitted picture with the EDGES block under it and the
pane scrolling normally.

## Done

- The graph pane is a React Flow canvas; `GraphRail.tsx` is gone from
  the tree, with `railRows` and the rail's five drawing components.
- Nodes carry their state, their detail line and their fan-out's branch
  chips; clicking one filters the log and right-clicking one offers
  rerun and move with the join's refusal printed.
- Forward and join edges run down the ranks, back edges bow out to the
  right with a `loop` label, and an edge this run never took is dashed.
- The header bar, the legend dots, EDGES, SOURCE and `open definition`
  are what they were.
- `GET /api/runs/{id}/graph` is untouched; `tests/snapshots` and
  `web/src/api/gen` are byte-identical.
- `@xyflow/react` is in `package.json` **and** `pnpm-lock.yaml`.
- 10 §Stack, 10 §Graph pane and 02 §Library choices say what the tree
  does; D32 is marked superseded and D206 is recorded.
- Gate green, including the axe floor with the canvas on screen.

## Out of scope (from the brief)

No change to the graph route, its response shape or any event. The
aside's markup, copy and styling stay as they are (only the classes that
place it beside the canvas move). The header bar and its legend dots
stay. The menu's two operations, their endpoints and their refusals stay.
The click-to-log interaction stays. No plugin node renderers and no
plugin-panel integration. No fallback to the rail and no preference to
switch back.

## Files

```
web/package.json
pnpm-lock.yaml                                (repo root)
web/src/panes/kinds/GraphCanvas.tsx          (new; replaces GraphRail.tsx)
web/src/panes/kinds/GraphRail.tsx            (deleted)
web/src/panes/kinds/graph.ts
web/src/panes/kinds/index.ts
web/src/plugins/registry.ts
web/src/index.css
web/src/styles/reactflow.css                 (new)
web/src/test-setup.ts
web/src/panes/__tests__/GraphCanvas.test.tsx (new; replaces GraphRail.test.tsx)
web/src/panes/__tests__/GraphRail.test.tsx   (deleted)
web/src/panes/__tests__/fixtures.ts
web/src/App.test.tsx
web/e2e/support/fixtures.ts
web/e2e/fanout.spec.ts
web/e2e/mobile.spec.ts
docs/v1/10-frontend.md
docs/v1/02-architecture.md
docs/v1/15-decisions.md
```
