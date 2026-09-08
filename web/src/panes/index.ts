/**
 * The pane host: which panes exist, the bar over them, and what one
 * draws (`docs/v1/10-frontend.md` §Panes, §Plugin renderers).
 *
 * What the shell reaches for. The pieces inside — a panel's source, the
 * kind renderers — are imported by path from within this directory;
 * nothing outside it needs them.
 */
export { PaneBar } from './PaneBar'
export { PaneRenderer } from './PaneRenderer'
export { BUILTIN_WORKFLOW, useManifest } from './manifest'
export { type PanelParams, type PanelScope } from './source'
export {
  paneLabel,
  panesOf,
  usePanes,
  JUMP_KEYS,
  type Pane,
  type PaneCursor,
  type PaneModel,
  type PaneScope,
} from './usePanes'
