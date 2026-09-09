/**
 * The custom-element table: which tag this build draws itself, and what
 * it draws it with (`docs/v1/09-plugins.md` §Escape hatch, §Builtins are
 * plugins).
 *
 * A `custom` panel names a tag. Two kinds of tag reach the pane host and
 * both arrive the same way — through the manifest, as data:
 *
 * - **the three the core ships** (`ath-agent-stream`, `ath-requests`,
 *   `ath-run-graph`) are declared by `athanore/plugins/builtin/` and
 *   drawn by React components in this bundle. They are registered here,
 *   at module load, and the host looks them up like anything else.
 * - **a plugin's own** is defined by the JavaScript its workflow ships
 *   (`assets=`), and is mounted as a real custom element by
 *   `src/panes/CustomElementHost.tsx`.
 *
 * That one table is the point. 09 says the builtins' *placement and
 * liveness* travel through the manifest "so the host page has no
 * hard-coded knowledge of them", and a lookup a plugin's tag could never
 * reach would be exactly that knowledge under another name. A build that
 * dropped the three registrations below would still draw a plugin's
 * element; a build with no registry at all could draw neither.
 *
 * `createElement` rather than JSX, and a `.ts` rather than a `.tsx`:
 * what is in this file is a table of three rows, not markup, and a
 * renderer is a plain function rather than a component because whether
 * the element brings its own scroller is a fact about what it returns
 * (`.oxlintrc.json`, `react/only-export-components`).
 */
import { createElement, type ReactNode } from 'react'

import { AgentStream, GraphRail, Requests } from '../panes/kinds'
import type { PanelScope } from '../panes/source'

/**
 * What a renderer draws, and whether it brings its own scroller.
 *
 * The three builtin elements all do: they virtualise or carry their own
 * header, so they need a viewport with a height rather than one that
 * grows with their content, and nesting them inside the pane's own
 * scroller would leave the virtualiser measuring a viewport that never
 * ends. A plugin's element is poured into the pane's, because a host
 * that gave a tag it has never seen the whole viewport would have no
 * way back if the element drew one line.
 */
export type ElementContent = { node: ReactNode; scrolls: boolean }

/**
 * What an element is drawn for: the scope its attributes come from, and
 * the two navigations the graph rail performs.
 *
 * A subset of `panes/content.tsx`'s `RenderContext` rather than the
 * whole of it, because a renderer is handed what an element can use —
 * and a plugin's element gets the scope alone, which is the same
 * boundary `window.athanore` draws (09: "Nothing else").
 */
export type ElementContext = {
  /** The ids the panel is drawn in (09 §Context and scopes). */
  scope: PanelScope
  /** Jump to the log pane filtered to a node; the graph's rows use it. */
  onOpenNode?: ((node: string) => void) | undefined
  /** `open definition`: the workflow library overlay (10 §Overlays). */
  onOpenLibrary?: (() => void) | undefined
}

/** How a tag this build knows is drawn. */
export type ElementRenderer = (ctx: ElementContext) => ElementContent

/**
 * The table itself, keyed by tag and not by workflow.
 *
 * A tag is a name for a renderer, so a plugin declaring `ath-run-graph`
 * means the graph rail: 09 gives the element vocabulary no namespace,
 * and a second table per workflow would make one tag two things.
 */
const RENDERERS = new Map<string, ElementRenderer>()

/**
 * Teach this build to draw `tag` itself.
 *
 * Called at module load for the three the core ships. A second
 * registration of one tag replaces the first, which is what a build
 * swapping a renderer does; nothing in the app does.
 */
export function registerElement(tag: string, renderer: ElementRenderer): void {
  RENDERERS.set(tag, renderer)
}

/** How to draw `tag`, or `undefined` when it is a plugin's own. */
export function elementRenderer(tag: string): ElementRenderer | undefined {
  return RENDERERS.get(tag)
}

/** Every tag this build draws itself, for a test and for a diagnostic. */
export function registeredElements(): string[] {
  return [...RENDERERS.keys()].sort()
}

// -- the elements the core ships (09 §Builtins are plugins) ---------------

// The agent pane.
registerElement('ath-agent-stream', (ctx) => ({
  scrolls: true,
  node: createElement(AgentStream, {
    runId: ctx.scope.runId,
    taskId: ctx.scope.taskId,
  }),
}))

// The same tag is both the run's requests pane and its `global` inbox
// twin (`athanore/plugins/builtin/requests.py`), because the table is
// keyed by tag: what differs between the two is the scope they are drawn
// in, and the renderer reads it.
registerElement('ath-requests', (ctx) => ({
  scrolls: true,
  node: createElement(Requests, { runId: ctx.scope.runId }),
}))

// The rail list of 10 §Graph pane. The EDGES column beside the rail is
// part of the pane's body rather than of a section poured into the
// host's scroller.
registerElement('ath-run-graph', (ctx) => ({
  scrolls: true,
  node: createElement(GraphRail, {
    runId: ctx.scope.runId,
    taskId: ctx.scope.taskId,
    onOpenNode: ctx.onOpenNode,
    onOpenLibrary: ctx.onOpenLibrary,
  }),
}))
