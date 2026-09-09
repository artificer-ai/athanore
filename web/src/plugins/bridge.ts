/**
 * `window.athanore`: the whole of what a plugin's web component may
 * reach (`docs/v1/09-plugins.md` §Escape hatch).
 *
 * ```ts
 * window.athanore = {
 *   fetch(path, init)                     // bound to /api/plugins/{wf}/, carries auth
 *   subscribe(names: string[], cb)        // the SSE feed, filtered
 *   theme: { tokens }                     // CSS custom properties, pierce shadow DOM
 * }
 * ```
 *
 * "Nothing else." Not the query client, not the router, not the store,
 * not `client.gen`'s typed operations — three capabilities, and each of
 * them is the app's own machinery with a narrow door on it:
 *
 * - **`fetch` is bound.** A path is resolved *under*
 *   `/api/plugins/{workflow}/` and a path that leaves that prefix is
 *   refused before a request is made, so a plugin reaches its own routes
 *   and no other part of the API. It carries the credential by the one
 *   rule `src/api/client.ts` applies to every typed call, because a
 *   plugin route is an operator route (12 §Plugins), and it reports a
 *   401 the way the response interceptor does — the token screen is
 *   owed whichever request found out.
 * - **`subscribe` is the tab's one stream**, filtered (10 §Realtime and
 *   caching). Not a second `EventSource`: that would be a second replay,
 *   a second keep-alive and a second reconnect storm for the same
 *   frames.
 * - **`theme.tokens` are values, not a stylesheet.** A custom element
 *   with a shadow root inherits the page's custom properties, but an
 *   element that builds a canvas, an SVG gradient or an inline style
 *   needs the *value*; handing over the resolved map is what 09 means by
 *   "pierce shadow DOM".
 *
 * **Which workflow the global is bound to.** `fetch` needs a workflow
 * and `window` is one object. The global resolves a relative path
 * against the workflow whose element was mounted most recently, which
 * is the only one there is in every deployment that has one plugin with
 * assets — and the pane cycle draws one pane at a time. Where two
 * workflows' elements *are* on screen at once, the host also hands each
 * element its own bridge as an `athanore` property on the element
 * itself: same three capabilities, bound unambiguously to that
 * element's workflow (D183).
 */
import { API_BASE_URL, apiAuthHeaders, reportUnauthorized } from '../api/client'
import type { AthanoreEvent } from '../realtime/invalidate'
import { appEventFeed } from '../realtime/sse'
import { THEME_TOKENS } from '../styles/tokens.gen'

/** Where a workflow's routes are mounted (08 §Plugins, 09 §Mounting). */
export function pluginPrefix(workflow: string): string {
  return `/api/plugins/${workflow}/`
}

/**
 * A base `URL` can be resolved against. The origin is thrown away — only
 * `pathname` and `search` are read — so it names nothing reachable.
 */
const RESOLUTION_ORIGIN = 'http://plugin.invalid'

declare global {
  interface Window {
    /**
     * What a plugin's web component reaches the host through, installed
     * by `src/panes/CustomElementHost.tsx` when the first plugin
     * element mounts (09 §Escape hatch).
     *
     * Optional because a document with no plugin element on it has
     * never needed one, which is every screen of a server with no
     * plugin that ships assets.
     */
    athanore?: Athanore
  }
}

/** The three capabilities, and nothing else (09 §Escape hatch). */
export type Athanore = {
  /** `GET`-by-default `fetch`, under this plugin's own prefix. */
  fetch: (path: string, init?: RequestInit) => Promise<Response>
  /** Events off the tab's one stream, filtered by name globs. */
  subscribe: (
    names: readonly string[],
    listener: (event: AthanoreEvent) => void,
  ) => () => void
  /** The design tokens, resolved (10 §Design system). */
  theme: { tokens: Record<string, string> }
}

/**
 * The theme's custom properties with their values, as the document
 * resolves them.
 *
 * Computed off `:root` rather than read out of `tokens.gen.ts` alone, so
 * a token an operator or a future theme overrides is what a plugin sees;
 * the generated value is the fallback for an environment that resolves
 * no styles at all (jsdom does not).
 */
export function themeTokens(): Record<string, string> {
  const computed = window.getComputedStyle(document.documentElement)
  const tokens: Record<string, string> = {}
  for (const token of THEME_TOKENS) {
    const resolved = computed.getPropertyValue(token.name).trim()
    tokens[token.name] = resolved === '' ? token.value : resolved
  }
  return tokens
}

/**
 * `path`, resolved under `workflow`'s prefix.
 *
 * `/words`, `words` and `words?limit=5` all name the same route; `..`,
 * an absolute URL and a protocol-relative `//host/x` do not name one at
 * all, and are refused here rather than sent. The refusal is a
 * `TypeError` because that is what a bad argument to a `fetch` is, and
 * it names the prefix so an author reads the boundary rather than
 * guessing at it.
 *
 * A leading `/` comes off so that `/words` and `words` are the same
 * route — but only when the path is not protocol-relative. `//host/x`
 * names another origin, and stripping its slashes would turn a request
 * that must be refused into a request to `{prefix}host/x` that quietly
 * succeeds; it is resolved as written instead, and refused for leaving
 * the prefix.
 */
export function pluginUrl(workflow: string, path: string): string {
  const prefix = pluginPrefix(workflow)
  const relative = path.startsWith('//') ? path : path.replace(/^\/+/, '')
  let resolved: URL
  try {
    resolved = new URL(relative, `${RESOLUTION_ORIGIN}${prefix}`)
  } catch {
    throw new TypeError(`athanore.fetch: ${path} is not a path`)
  }
  if (`${resolved.origin}${resolved.pathname}`.startsWith(RESOLUTION_ORIGIN + prefix)) {
    return `${API_BASE_URL}${resolved.pathname}${resolved.search}`
  }
  throw new TypeError(
    `athanore.fetch is bound to ${prefix}; ${path} leaves it. A plugin ` +
      `reaches its own routes and no others (09 §Escape hatch).`,
  )
}

/**
 * The bridge for one workflow: what the host puts on the element itself.
 *
 * The same three capabilities as the global, with `fetch` bound to this
 * workflow and to no other — so an element that reads `this.athanore`
 * is right whatever else is on screen (D183).
 *
 * Frozen, because the surface is the contract: an element that added a
 * key to it would be writing on the host.
 */
export function pluginBridge(workflow: string): Athanore {
  return Object.freeze({
    fetch: (path: string, init?: RequestInit) => request(workflow, path, init),
    subscribe,
    theme: { tokens: themeTokens() },
  })
}


/**
 * Keep `window.athanore` installed for as long as an element is on
 * screen, and say which workflow it is currently bound to.
 *
 * Called from the host's mount effect and released from its cleanup, so
 * the list holds exactly the plugin elements that are drawn. The global
 * itself is installed once and never removed: a module that already ran
 * may reach for it at any time, and a global that came and went would
 * be a race a plugin author could not see.
 */
const mounted: { workflow: string }[] = []

export function bindPluginBridge(workflow: string): () => void {
  const entry = { workflow }
  mounted.push(entry)
  installGlobal()
  return () => {
    const at = mounted.lastIndexOf(entry)
    if (at !== -1) mounted.splice(at, 1)
  }
}

/**
 * The workflow `window.athanore.fetch` resolves a relative path against:
 * the one whose element was mounted last.
 *
 * `subscribe` and `theme` are the same for every plugin, so this decides
 * nothing but the prefix — and an element that must be certain of its
 * own reads the bridge the host put on it rather than the global
 * (D183).
 */
function currentWorkflow(): string | undefined {
  return mounted.at(-1)?.workflow
}

/** The object on `window.athanore`, made once. */
let installed: Athanore | null = null

function installGlobal(): void {
  installed ??= Object.freeze({
    fetch(path: string, init?: RequestInit): Promise<Response> {
      const workflow = currentWorkflow()
      if (workflow === undefined) {
        return Promise.reject(
          new TypeError(
            'athanore.fetch: no plugin element is mounted, so there is no ' +
              'prefix to resolve against (09 §Escape hatch)',
          ),
        )
      }
      return request(workflow, path, init)
    },
    subscribe,
    theme: { tokens: themeTokens() },
  })
  // Assigned rather than assumed: the object is made once, but a
  // document that lost the property — a test that cleared it, a script
  // that overwrote it — gets it back on the next element that mounts.
  if (window.athanore !== installed) window.athanore = installed
}

/** `GET path` under `workflow`'s prefix, with the operator credential. */
async function request(
  workflow: string,
  path: string,
  init?: RequestInit,
): Promise<Response> {
  const url = pluginUrl(workflow, path)
  const headers = new Headers(init?.headers)
  for (const [header, value] of Object.entries(apiAuthHeaders())) {
    headers.set(header, value)
  }
  const response = await fetch(url, { ...init, headers })
  reportUnauthorized(response.status)
  return response
}

/** The tab's one stream, filtered (10 §Realtime and caching). */
function subscribe(
  names: readonly string[],
  listener: (event: AthanoreEvent) => void,
): () => void {
  const feed = appEventFeed()
  if (feed === null) {
    // Not a silent no-op: an element that believed it was subscribed
    // would sit there stale, and the reason — no feed open in this
    // document — is one the caller can act on.
    throw new Error(
      'athanore.subscribe: this document has no event feed open ' +
        '(the SPA opens one per tab; see 10 §Realtime and caching)',
    )
  }
  return feed.subscribe(names, listener)
}
