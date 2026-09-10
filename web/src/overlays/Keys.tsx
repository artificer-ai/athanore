/**
 * The keys overlay (`?`, and the palette's `keys` row): "the footer
 * chips, expanded" (`docs/v1/10-frontend.md` §Overlays).
 *
 * Expanded in two directions. The footer strip has room for fourteen
 * chips and 10 §Keyboard has twenty-three bindings, so this panel is the
 * whole map — the arrows, the digits, `⏎`, `^p`, `^r`, `esc` and the
 * request panel's `a`/`d` that the strip has no room for — and it draws
 * each row's scope beside it, which a chip cannot carry at all.
 *
 * **It lists the table, it does not restate it.** `lib/keys.ts` is 10
 * §Keyboard transcribed once, and this file walks it: a binding added
 * there appears here without anyone remembering to add it, which is the
 * only way "lists every binding" stays true after this task. The section
 * headings are the table's groups, and the rows inside one keep the
 * order 10 writes them in.
 *
 * The rules under the sections are {@link KEY_NOTES} — the two sentences
 * 10 §Keyboard states *about* the map. An operator who cannot work out
 * why `t` did nothing while they were typing a run title has not been
 * shown the map, only its rows.
 */
import {
  capLabel,
  KEY_BINDINGS,
  KEY_GROUPS,
  KEY_NOTES,
  type KeyBinding,
} from '../lib/keys'
import { OverlayDialog, OverlayHeader } from './OverlayPanel'

/** The dialog's accessible name, and the panel's header kicker. */
export const KEYS_TITLE = 'keys'

/** The header's gloss: what the panel is, in the mock's register. */
export const KEYS_GLOSS = 'the whole map of 10 §Keyboard'

/** A keycap chip, the footer's (`components/Footer.tsx`). */
function Kbd({ children }: { children: string }) {
  return (
    <kbd className="text-hint rounded-lg border border-border bg-[var(--color-neutral-900)] px-[4px] font-mono text-[var(--color-accent-300)]">
      {children}
    </kbd>
  )
}

/** One binding: its caps, what it does, and when it applies. */
function Row({ binding }: { binding: KeyBinding }) {
  return (
    <div
      data-testid="key-row"
      data-binding={binding.id}
      className="grid grid-cols-[minmax(0,132px)_minmax(0,1fr)] items-baseline gap-[10px] border-t border-[var(--color-neutral-900)] px-[14px] py-[5px]"
    >
      <span className="flex flex-wrap items-center gap-[4px]">
        {binding.keys.map((key) => (
          <Kbd key={key}>{capLabel(key)}</Kbd>
        ))}
      </span>
      <span className="text-row text-[var(--color-neutral-300)]">
        {binding.label}
        {binding.note !== '' && (
          <span className="text-hint ml-[6px] text-muted-foreground">
            {binding.note}
          </span>
        )}
      </span>
    </div>
  )
}

export function Keys({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <OverlayDialog
      open={open}
      onClose={onClose}
      testId="keys"
      width="w-[min(560px,92vw)]"
      placement="top"
    >
      <OverlayHeader title={KEYS_TITLE} gloss={KEYS_GLOSS} hint="esc close" />

      <div className="min-h-0 flex-1 overflow-auto pb-[4px]">
        {KEY_GROUPS.map((group) => {
          const bindings = KEY_BINDINGS.filter((binding) => binding.group === group)
          if (bindings.length === 0) return null
          return (
            <section key={group} data-testid="key-group" data-group={group}>
              <h3 className="text-kicker border-t border-[var(--color-neutral-900)] px-[14px] pt-[9px] pb-[3px] text-[var(--color-neutral-500)]">
                {group}
              </h3>
              {bindings.map((binding) => (
                <Row key={binding.id} binding={binding} />
              ))}
            </section>
          )
        })}

        <ul
          data-testid="key-notes"
          className="text-hint mt-[8px] flex flex-col gap-[3px] border-t border-[var(--color-neutral-900)] px-[14px] pt-[9px] text-muted-foreground"
        >
          {KEY_NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </div>
    </OverlayDialog>
  )
}
