/**
 * The overlay chrome, as three pieces: the backdrop, the panel on it,
 * and the button in the panel.
 *
 * The section fixes all of it — a full-screen `rgba(10,11,18,.72)`
 * backdrop, a surface panel with a 1 px neutral-800 border, an 8 px
 * radius and `--shadow-lg` — so the values live in one module and the
 * screens that stand between the operator and the app (`AppGate`'s two
 * notices, `TokenScreen`) draw the same rectangle rather than two
 * copies of one that drift.
 *
 * These are the *curtains*: overlays with nothing behind them and no way
 * past them but the server answering differently. The dismissible
 * overlays of §Overlays — the palette, the pickers, the drawer — are
 * `Dialog`s and are T066's; they share this look, not this module.
 */
import type { ReactNode } from 'react'

/** A full-screen backdrop with its panel centred. */
export function Curtain({ children }: { children: ReactNode }) {
  return (
    <div
      data-testid="app-gate-curtain"
      className="flex h-dvh items-center justify-center bg-[rgba(10,11,18,.72)] p-[24px]"
    >
      {children}
    </div>
  )
}

/**
 * The overlay surface, headed by its kicker.
 *
 * The kicker is also the panel's accessible name: it is the two or three
 * words that say which curtain this is, which is exactly what a screen
 * reader announcing the dialog should say.
 */
export function CurtainPanel({
  kicker,
  children,
}: {
  kicker: string
  children: ReactNode
}) {
  return (
    <div
      role="dialog"
      aria-label={kicker}
      className="flex w-full max-w-[460px] flex-col gap-[10px] rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-surface)] p-[18px] shadow-[var(--shadow-lg)]"
    >
      <h2 className="text-kicker text-[var(--color-accent-300)]">{kicker}</h2>
      {children}
    </div>
  )
}

/** A command the operator types, or a path they can go and read. */
export function CurtainCode({ children }: { children: ReactNode }) {
  return (
    <code className="text-meta rounded-sm bg-[var(--color-neutral-900)] px-[4px] py-px text-[var(--color-accent-200)]">
      {children}
    </code>
  )
}

/** The outlined button of 10 §Components, in a curtain's proportions. */
export function CurtainButton({
  type = 'button',
  disabled = false,
  onClick,
  children,
}: {
  type?: 'button' | 'submit'
  disabled?: boolean
  onClick?: (() => void) | undefined
  children: ReactNode
}) {
  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      className="text-meta cursor-pointer self-start rounded-lg border border-border px-[10px] py-[4px] text-[var(--color-accent-200)] hover:border-[var(--color-accent-600)] hover:bg-[var(--color-accent-900)] disabled:cursor-default disabled:opacity-50 disabled:hover:border-border disabled:hover:bg-transparent"
    >
      {children}
    </button>
  )
}
