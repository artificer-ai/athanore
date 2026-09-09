/**
 * A plugin's JavaScript, injected once (`docs/v1/09-plugins.md` §Escape
 * hatch).
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
 * Inject every asset in `urls` that this document does not already have.
 *
 * A script that fails to load is reported and nothing else happens: the
 * element it would have defined never appears, and the pane draws the
 * placeholder it draws for a tag this build cannot mount. A plugin's
 * broken build is not the app's crash.
 */
export function injectAssets(urls: readonly string[]): void {
  for (const url of urls) {
    if (assetLoaded(url)) continue
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
