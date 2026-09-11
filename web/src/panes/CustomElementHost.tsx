/**
 * A `custom` panel this build has no renderer for: the plugin's own web
 * component, mounted.
 *
 * "A `custom` panel renders `<the-tag run-id=… task-id=… node=…>` inside
 * a thin React wrapper." This is the wrapper, and thin is the whole
 * specification of it: it injects the workflow's assets once, gives the
 * element the three capabilities of `window.athanore`, and renders the
 * tag with the scope on it. It does not style the element, does not
 * reach inside it, and does not know one tag from another — the tags
 * this build *does* draw itself resolve through `src/plugins/registry.ts`
 * before anything gets here, which is what keeps the host free of
 * hard-coded pane knowledge (09 §Builtins are plugins).
 *
 * **Why the element is not JSX.** `connectedCallback` runs the instant a
 * *defined* element is inserted into the document, and React inserts a
 * host node before it attaches refs and long before it runs effects. So
 * an element rendered as JSX would be connected — and would read
 * `this.athanore` and `window.athanore` — before either existed. The
 * first mount in a document happens to survive that, because the tag is
 * still undefined and the browser defers `connectedCallback` to the
 * `customElements.define` upgrade; every mount after it, which is what
 * the pane bar does every time an operator cycles back to the pane,
 * would not. The host therefore owns the insertion: React draws an empty
 * wrapper, and a mount effect binds `window.athanore`, builds the
 * element, puts its own bridge and the scope on it, and only then
 * appends it. Nothing a plugin can read is unset when its first line
 * runs, on any mount.
 *
 * The wrapper is `display: contents`, so it is a place to insert into
 * and not a box: the element lays out inside the pane exactly as it did
 * when React rendered the tag itself.
 *
 * **The scope is set, not remounted.** A selection change writes
 * `run-id` / `task-id` / `node` onto the element that is already there —
 * `attributeChangedCallback` is how a web component follows the
 * selection, and tearing the element down would throw away whatever it
 * had built. Only the tag, the workflow or the workflow's asset *paths*
 * changing rebuilds it: a manifest refetched after a reload of the
 * workflow lists the same file at a new `?v=` (22 §Live mounting), and
 * that is neither a new asset to inject — a module this document has
 * run cannot run again, D225 — nor a reason to rebuild the element. The
 * host keeps drawing the one it has; the shell's notice says the code
 * moved (`panes/manifest.ts`, D253). A path added or taken away is a
 * different asset list and rebuilds as before.
 *
 * **What it draws when there is nothing to mount.** A workflow that
 * ships no assets can define no element, so the tag would sit there
 * empty forever. The pane says so instead — the same degradation 09
 * gives an unknown `kind`, "a placeholder card, never a crash" — unless
 * the tag is already defined, which is the case where some other pane's
 * assets brought it.
 */
import { useEffect, useMemo, useRef } from 'react'

import { PlaceholderCard } from './kinds'
import { useManifestEntries } from './manifest'
import type { PanelScope } from './source'
import { assetPath, bindPluginBridge, injectAssets, pluginBridge } from '../plugins'

/** An element with the bridge the host put on it (09 §Escape hatch). */
type PluginElement = HTMLElement & { athanore?: ReturnType<typeof pluginBridge> }

/**
 * The attributes 09 §Escape hatch names, and only those.
 *
 * `undefined` is "the scope has no value for this one", which is an
 * absent attribute rather than the string `"undefined"` — the same thing
 * React does with an `undefined` prop.
 */
type ScopeAttributes = {
  'run-id': string | undefined
  'task-id': string | undefined
  node: string | undefined
}

/** Whether `tag` is already a defined custom element in this document. */
function defined(tag: string): boolean {
  return typeof customElements !== 'undefined' && customElements.get(tag) !== undefined
}

/** Write `scope` onto `element`, taking off what it has no value for. */
function applyScope(element: HTMLElement, scope: ScopeAttributes): void {
  for (const [name, value] of Object.entries(scope)) {
    if (value === undefined) element.removeAttribute(name)
    else element.setAttribute(name, value)
  }
}

export function CustomElementHost({
  tag,
  workflow,
  scope,
  node,
}: {
  /** The `element` the manifest's panel names. */
  tag: string
  /** The workflow that declared the panel: whose assets, whose prefix. */
  workflow: string
  /** `run-id` and `task-id`, from the selection (09 §Context and scopes). */
  scope: PanelScope
  /** `node`, for a panel that follows one. */
  node?: string | undefined
}) {
  const { manifest } = useManifestEntries()
  const assets = useMemo(
    () => manifest.find((entry) => entry.workflow === workflow)?.assets ?? [],
    [manifest, workflow],
  )
  const attributes = useMemo<ScopeAttributes>(
    () => ({
      'run-id': scope.runId,
      'task-id': scope.taskId === undefined ? undefined : String(scope.taskId),
      node,
    }),
    [scope.runId, scope.taskId, node],
  )
  // The scope the element is built with, kept out of the mount effect's
  // dependencies: the element's lifetime is the pane's, and a selection
  // change writes attributes onto the element that is already there.
  const latest = useRef(attributes)
  // The assets too, for the same reason one step over: the effect is
  // keyed on their *paths*, so a `?v=` bump does not re-run it, and the
  // list it injects on a real change is the current one.
  const latestAssets = useRef(assets)
  const assetPaths = assets.map(assetPath).join('\n')
  const wrapper = useRef<HTMLDivElement | null>(null)
  const element = useRef<PluginElement | null>(null)
  const nothing = assets.length === 0 && !defined(tag)

  // Declared before the mount effect so that in a commit which runs
  // both — the workflow changed and the selection with it — this one has
  // written `latest` by the time the element below is built from it.
  useEffect(() => {
    latest.current = attributes
    if (element.current !== null) applyScope(element.current, attributes)
  }, [attributes])

  useEffect(() => {
    latestAssets.current = assets
  }, [assets])

  useEffect(() => {
    const parent = wrapper.current
    if (parent === null) return
    // The global first, then the element's own bridge and its scope,
    // and only then the insertion that runs `connectedCallback` — every
    // one of them is something the plugin's first line may read (09
    // §Escape hatch).
    const release = bindPluginBridge(workflow)
    const mounted: PluginElement = document.createElement(tag)
    mounted.athanore = pluginBridge(workflow)
    mounted.dataset.testid = 'plugin-element'
    mounted.dataset.element = tag
    mounted.dataset.workflow = workflow
    applyScope(mounted, latest.current)
    element.current = mounted
    parent.append(mounted)
    // Last: this is the only line here that can run a plugin's code, and
    // everything that code reads is in place above it.
    injectAssets(latestAssets.current)
    return () => {
      mounted.remove()
      element.current = null
      release()
    }
  }, [tag, workflow, assetPaths, nothing])

  if (nothing) {
    return (
      <PlaceholderCard
        title="this panel is a plugin element with nothing to define it"
        detail={`<${tag}> · ${workflow} ships no assets`}
      />
    )
  }

  // `contents`: the wrapper is where the element goes, not a box around
  // it. Nothing here styles a plugin's element.
  return <div ref={wrapper} className="contents" data-testid="plugin-host" />
}
