/**
 * The overlays of `docs/v1/10-frontend.md` §Overlays: the dismissible
 * dialogs `?overlay=` drives, as against the curtains of
 * `components/Curtain.tsx`, which have nothing behind them.
 */
export { Palette, PALETTE_TITLE } from './Palette'
export {
  PALETTE_COMMANDS,
  buildPaletteActions,
  groupActions,
  type PaletteAction,
  type PaletteContext,
} from './actions'
