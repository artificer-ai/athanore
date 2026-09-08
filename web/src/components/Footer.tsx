/**
 * The footer strip: the key-hint chips and the `^p palette` button
 * (`docs/v1/10-frontend.md` §Layout and §Keyboard).
 *
 * The chips are the mock's row with one correction the spec makes:
 * delete is `D`, not `d`, so that a `d` meant for "deny" one focus ring
 * away cannot reach the delete confirm (10 §Keyboard). The full map —
 * arrows, digits, `esc` — is the `?` overlay's (T066e); these are the
 * hints that fit on one line. Binding the keys themselves is T067's.
 */
import type { ReactNode } from 'react'

/**
 * The footer's hints, in the mock's order (10 §Keyboard). Not exported:
 * the keyboard map itself is T067's, and this is the strip's copy.
 */
const KEY_HINTS: ReadonlyArray<readonly [string, string]> = [
  ['tab', 'focus'],
  ['t', 'retry task'],
  ['m', 'move task'],
  ['x', 'cancel task'],
  ['l', 'append log'],
  ['n', 'new run'],
  ['r', 'rerun node'],
  ['p', 'pause/resume'],
  ['c', 'cancel run'],
  ['D', 'delete run'],
  ['e', 'edit run'],
  ['w', 'workflows'],
  ['b', 'toggle list'],
  ['?', 'keys'],
]

/** A keycap chip: neutral-900 on a neutral-800 rule, accent-300 text. */
function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="text-hint rounded-lg border border-border bg-[var(--color-neutral-900)] px-[4px] font-mono text-[var(--color-accent-300)]">
      {children}
    </kbd>
  )
}

export function Footer({ onOpenPalette }: { onOpenPalette: () => void }) {
  return (
    <footer className="bg-chrome flex flex-none flex-wrap items-center gap-[12px] border-t border-border px-[12px] py-[5px]">
      {KEY_HINTS.map(([key, label]) => (
        <span key={key} className="inline-flex items-center gap-[5px]">
          <Kbd>{key}</Kbd>
          <span className="text-hint text-muted-foreground">{label}</span>
        </span>
      ))}

      <div className="flex-1" />

      <button
        type="button"
        onClick={onOpenPalette}
        className="inline-flex items-center gap-[6px] rounded-lg border border-border px-[8px] py-[2px] hover:border-[var(--color-accent-600)]"
      >
        <span className="text-hint text-[var(--color-accent-300)]">^p</span>
        <span className="text-hint text-muted-foreground">palette</span>
      </button>
    </footer>
  )
}
