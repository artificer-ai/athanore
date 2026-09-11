/**
 * The command palette (`^p` / `⌘p`): cmdk's `Command` inside a Radix
 * `Dialog`, drawn as the mock draws it — "Palette | `Command` (cmdk) in
 * a `Dialog`".
 *
 * A `›` prompt, one input, and rows of `name · hint · key`. The key
 * column is why every action is listed whether or not the operator can
 * run it right now: the palette is the app's index of itself, so it
 * doubles as the shortcut list, and a row that came and went with the
 * selection would make it a worse one. What is in the catalogue and what
 * disables a row is `./actions.ts`; this file is how it looks and how it
 * is driven.
 *
 * Rows carry a `group`, and consecutive rows sharing one are drawn under
 * it in a `Command.Group` (`groupActions`, `./actions.ts`). The app's own
 * commands have no group — the mock lists them as one flat run of rows —
 * and plugin actions arrive under `plugin: <title>` when there are any
 * (T070).
 *
 * Three things the dialog gives us that a `div` would not, and all three
 * are the reason 10 §Accessibility asks for Radix: `esc` closes it,
 * focus is trapped inside it while it is up, and focus returns to
 * whatever had it when it opened — the footer's `^p` button, a run row,
 * the key the operator pressed from. Keyboard users are the ones who
 * live in a palette; landing them back on `<body>` would cost them their
 * place in the app every time they opened it.
 *
 * That last one is handed to us only halfway. A modal Radix dialog puts
 * focus back on its `Dialog.Trigger`, and this one has no trigger: it
 * opens from `?overlay=palette`, which a footer button, a keystroke and
 * a pasted link all write. So the two ends of the round trip are ours —
 * the element that had focus is read when the dialog takes it and given
 * it back when the dialog lets go — and what opened the palette is
 * whatever the operator was on, not one blessed button.
 */
import { Command } from 'cmdk'
import { Dialog, VisuallyHidden } from 'radix-ui'
import { useRef } from 'react'

import { useKeyOwner } from '../keys'
import { capLabel } from '../lib/keys'
import { groupActions, type PaletteAction } from './actions'
import { OverlayClose } from './OverlayPanel'

/** The dialog's accessible name, and cmdk's label for the listbox. */
export const PALETTE_TITLE = 'command palette'

/** The mock's placeholder. */
const PLACEHOLDER = 'run a command'

export function Palette({
  open,
  actions,
  onClose,
}: {
  open: boolean
  actions: readonly PaletteAction[]
  onClose: () => void
}) {
  const sections = groupActions(actions)
  // An open overlay owns the keyboard: while it is up the app's global
  // map is off, so a `d` in here cannot reach the delete confirm
  // (`keys/scope.ts`, 10 §Keyboard).
  useKeyOwner(open)
  const restoreFocusTo = useRef<HTMLElement | null>(null)
  const input = useRef<HTMLInputElement | null>(null)

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        // Radix reports every dismissal the same way — `esc`, a click on
        // the backdrop, a click outside the panel — so there is one way
        // out of here and the app writes `?overlay=` away once.
        if (!next) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          data-testid="palette-backdrop"
          className="fixed inset-0 z-40 bg-[rgba(10,11,18,.72)]"
        />

        <Dialog.Content
          data-testid="palette"
          // The palette says what it is in two words and describes
          // nothing further; without this Radix warns about the
          // description it cannot find.
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // Radix is about to focus the first thing in the panel. It
            // has not yet, so this is the last moment at which the
            // element the operator was on is still the focused one.
            event.preventDefault()
            restoreFocusTo.current =
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null
            input.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            // Radix's own restore goes to a trigger this dialog has not
            // got, which is `<body>` — the operator's place in the app,
            // lost. Ours goes back where focus came from.
            event.preventDefault()
            restoreFocusTo.current?.focus()
            restoreFocusTo.current = null
          }}
          className="text-body fixed top-[12vh] left-1/2 z-50 w-[min(560px,92vw)] -translate-x-1/2 overflow-hidden rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-surface)] text-foreground shadow-[var(--shadow-lg)] max-md:top-[8px] max-md:w-[calc(100vw-16px)] max-md:max-w-[calc(100vw-16px)]"
        >
          <VisuallyHidden.Root asChild>
            <Dialog.Title>{PALETTE_TITLE}</Dialog.Title>
          </VisuallyHidden.Root>

          <Command label={PALETTE_TITLE} loop>
            <div className="flex items-center gap-[8px] border-b border-[var(--color-neutral-900)] px-[12px] py-[9px]">
              <span aria-hidden className="text-[var(--color-accent-400)]">
                ›
              </span>
              <Command.Input
                ref={input}
                placeholder={PLACEHOLDER}
                aria-label={PALETTE_TITLE}
                className="text-body flex-1 bg-transparent text-foreground outline-none placeholder:text-[var(--color-neutral-500)]"
              />
              <span className="text-hint text-muted-foreground max-md:hidden">esc</span>
              <OverlayClose />
            </div>

            <Command.List className="max-h-[300px] overflow-auto max-md:max-h-[calc(100dvh-90px)]">
              <Command.Empty className="text-row px-[12px] py-[10px] text-muted-foreground">
                no command matches
              </Command.Empty>

              {sections.map((section) => (
                <Command.Group
                  key={section.group ?? '_app'}
                  value={section.group ?? '_app'}
                  {...(section.group === null ? {} : { heading: section.group })}
                  className="[&_[cmdk-group-heading]]:text-kicker [&_[cmdk-group-heading]]:border-t [&_[cmdk-group-heading]]:border-[var(--color-neutral-900)] [&_[cmdk-group-heading]]:px-[12px] [&_[cmdk-group-heading]]:pt-[8px] [&_[cmdk-group-heading]]:pb-[4px] [&_[cmdk-group-heading]]:text-[var(--color-neutral-500)]"
                >
                  {section.actions.map((action) => (
                    <Command.Item
                      key={action.id}
                      value={action.name}
                      // Both spellings of the cap: the operator who
                      // types `D` finds the row, and so does the one
                      // who reads `⇧D` off the strip and types `⇧`.
                      keywords={[action.hint, action.key, capLabel(action.key)]}
                      disabled={action.disabled}
                      onSelect={action.run}
                      className="text-row grid cursor-pointer grid-cols-[minmax(0,170px)_minmax(0,1fr)_40px] items-center gap-[10px] border-t border-[var(--color-neutral-900)] px-[12px] py-[6px] data-[disabled=true]:cursor-default data-[disabled=true]:opacity-45 data-[selected=true]:bg-[var(--color-neutral-900)] max-md:min-h-[32px]"
                    >
                      <span className="text-[var(--color-neutral-300)]">
                        {action.name}
                      </span>
                      <span className="text-hint text-muted-foreground">
                        {action.hint}
                      </span>
                      <span className="text-hint text-[var(--color-accent-300)]">
                        {capLabel(action.key)}
                      </span>
                    </Command.Item>
                  ))}
                </Command.Group>
              ))}
            </Command.List>
          </Command>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
