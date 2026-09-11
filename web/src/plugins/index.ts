/**
 * The plugin seam on the browser's side: the element table, the assets
 * a workflow ships, and `window.athanore`.
 *
 * What the pane host reaches for. 09 §Escape hatch is the whole of the
 * contract — a plugin ships a `.js`, the host mounts its tag, and the
 * element gets three capabilities and nothing else — and the three
 * modules behind this file are one of those each.
 */
export {
  ASSET_ATTRIBUTE,
  assetLoaded,
  assetPath,
  injectAssets,
  injectedAssets,
  staleAssets,
} from './assets'
export {
  bindPluginBridge,
  pluginBridge,
  pluginPrefix,
  pluginUrl,
  themeTokens,
  type Athanore,
} from './bridge'
export {
  elementRenderer,
  registerElement,
  registeredElements,
  type ElementContent,
  type ElementContext,
  type ElementRenderer,
} from './registry'
