/**
 * A plugin's JavaScript, injected once.
 *
 * The manifest carries `assets: [urls]` per workflow — every `.js` under
 * the directory the workflow declared, served by the server at
 * `/plugins/{wf}/static/` — and the SPA "injects them once as
 * `<script type="module">`".
 *
 * Three things that sentence decides:
 *
 * - **once, and never removed.** A module cannot be un-executed: a
 *   script torn down with the pane that needed it and injected again on
 *   the next mount would run its `customElements.define` a second time
 *   and throw. So a loaded asset stays loaded for the life of the
 *   document.
 * - **the document is the record.** Whether a URL is already loaded is
 *   asked of `document.head`, not of a module-level set, so there is one
 *   answer rather than two that can disagree — a second SPA mounted in
 *   one document, a test that swapped the document out — and the check
 *   is true even for a script some other code put there.
 * - **`type="module"`, `src`, and nothing inline.** 12 §Plugins' policy
 *   is `script-src 'self'`: a same-origin `src` loads, an inline script
 *   would not, and there is nothing here that writes one.
 * - **a second version of one path is never injected.** A manifest URL
 *   carries the file's content version as `?v=` (22 §Live mounting), so
 *   a workflow reloaded with different JavaScript lists a URL whose
 *   *path* this document already ran under another `?v=`. Injecting it
 *   would run the plugin's `customElements.define` a second time and
 *   throw inside its module; the document cannot follow, and says so
 *   instead — {@link staleAssets} is what finds those URLs, the shell
 *   raises the notice (`components/PluginAssetsBanner.tsx`), and a
 *   reload is the only thing that makes a new document (D225).
 *
 * There is no guard for a document that does not exist. This is a
 * browser SPA and nothing renders it anywhere else (10 §Stack), and a
 * branch no environment takes is a branch no test can reach.
 */

/** The attribute that marks a script as one of ours, and names it. */
export const ASSET_ATTRIBUTE = 'data-athanore-asset'

/** Whether `url` has already been injected into this document. */
export function assetLoaded(url: string): boolean {
  return document.head.querySelector(`script[${ASSET_ATTRIBUTE}="${url}"]`) !== null
}

/**
 * The part of an asset URL that names the file: everything before its
 * first `?`.
 *
 * Two manifest URLs with one path are one module at two content
 * versions (22 §Live mounting), which is the whole of what the banner
 * and the pane host need to know about a URL.
 */
export function assetPath(url: string): string {
  const query = url.indexOf('?')
  return query < 0 ? url : url.slice(0, query)
}

/**
 * The URLs in `urls` whose path this document has already injected
 * under a different full URL — the same file at another `?v=`.
 *
 * Read from the document, as {@link assetLoaded} reads. Empty for a
 * first injection (the path is absent), for an identical list (the
 * full URL is what is loaded), and for a removal (nothing new is
 * listed); a workflow that is reloaded with the same bytes lists the
 * same `?v=` and is not stale either.
 */
export function staleAssets(urls: readonly string[]): string[] {
  const loaded = new Map(injectedAssets().map((url) => [assetPath(url), url]))
  return urls.filter((url) => {
    const current = loaded.get(assetPath(url))
    return current !== undefined && current !== url
  })
}

/**
 * Inject every asset in `urls` that this document does not already have.
 *
 * A URL whose path is loaded under another `?v=` is skipped too: never
 * a second version of one module (D225). The pane host keys its mount
 * on asset paths so that such a URL does not reach here; this is the
 * last line of defence, not the first.
 *
 * A script that fails to load is reported and nothing else happens: the
 * element it would have defined never appears, and the pane draws the
 * placeholder it draws for a tag this build cannot mount. A plugin's
 * broken build is not the app's crash.
 */
export function injectAssets(urls: readonly string[]): void {
  const stale = new Set(staleAssets(urls))
  for (const url of urls) {
    if (assetLoaded(url) || stale.has(url)) continue
    const script = document.createElement('script')
    script.type = 'module'
    script.setAttribute(ASSET_ATTRIBUTE, url)
    script.addEventListener('error', () => {
      console.error(`athanore: a plugin asset failed to load: ${url}`)
    })
    // `src` last: setting it is what starts the fetch, and the listener
    // has to be on before that.
    script.src = url
    document.head.append(script)
  }
}

/** Every plugin asset this document has loaded, in injection order. */
export function injectedAssets(): string[] {
  return [...document.head.querySelectorAll(`script[${ASSET_ATTRIBUTE}]`)].map(
    (script) => script.getAttribute(ASSET_ATTRIBUTE) ?? '',
  )
}
