/**
 * The dialog chrome the overlays of `docs/v1/10-frontend.md` §Overlays
 * share: a `rgba(10,11,18,.72)` backdrop, a surface panel with a 1 px
 * neutral-800 border, an 8 px radius and `--shadow-lg`, and a header
 * strip of `kicker · gloss … hint`.
 *
 * `components/Curtain.tsx` draws the same rectangle for the screens that
 * stand *instead of* the app; this one is for the dismissible dialogs
 * that stand *over* it, and the difference is everything Radix brings:
 * `esc` closes it, focus is trapped inside it, and focus goes back where
 * it came from when it lets go.
 *
 * **The focus round trip is ours.** A modal Radix dialog restores focus
 * to its `Dialog.Trigger`; these open from `?overlay=`, which a footer
 * button, a keystroke and a pasted link all write, so there is no
 * trigger and Radix's restore lands on `<body>` — the operator's place
 * in the app, lost. The element that had focus is therefore read at the
 * last moment it still has it and given it back on close.
 *
 * The four overlays T066a–T066d built keep their own copies of this
 * dance, because two of them thread a caret through a form that mounts
 * after the panel does (`./NewRun.tsx`) and rewriting them is not this
 * task; the three overlays that have nothing to thread share it here
 * rather than making three more copies (D175).
 */
import { Dialog } from 'radix-ui'
import { useRef, type ReactNode, type RefObject } from 'react'

import { useKeyOwner } from '../keys'

/** Where the panel sits: near the top like a palette, or centred. */
export type OverlayPlacement = 'top' | 'centre'

/**
 * Where the panel sits and how tall it may get.
 *
 * The two go together: a panel pinned 12 vh down may not also be a
 * viewport tall, or its last rows fall off the bottom of the screen with
 * nothing to scroll them back — which is the palette's `76vh`
 * (`./Pickers.tsx`), and the reason this is one table and not two.
 */
const PLACEMENTS: Record<OverlayPlacement, string> = {
  top: 'top-[12vh] left-1/2 -translate-x-1/2 max-h-[76vh]',
  centre:
    'top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 max-h-[calc(100dvh-48px)]',
}

export function OverlayDialog({
  open,
  onClose,
  testId,
  width,
  placement = 'centre',
  focusRef,
  children,
}: {
  open: boolean
  onClose: () => void
  /** `data-testid` on the panel; the backdrop gets `<testId>-backdrop`. */
  testId: string
  /** The panel's width utility, which differs per overlay. */
  width: string
  placement?: OverlayPlacement
  /**
   * What takes focus when the panel opens. Defaults to the panel, which
   * is what a dialog with nothing to type in wants.
   */
  focusRef?: RefObject<HTMLElement | null> | undefined
  children: ReactNode
}) {
  // An open overlay owns the keyboard: while it is up the app's global
  // map is off, so a `d` in here cannot reach the delete confirm
  // (`keys/scope.ts`, 10 §Keyboard).
  useKeyOwner(open)

  const restoreFocusTo = useRef<HTMLElement | null>(null)
  const panel = useRef<HTMLDivElement | null>(null)

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        // `esc`, the backdrop and a click outside all arrive here, so
        // there is one way out and the app writes `?overlay=` away once.
        if (!next) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          data-testid={`${testId}-backdrop`}
          className="fixed inset-0 z-40 bg-[rgba(10,11,18,.72)]"
        />

        <Dialog.Content
          ref={panel}
          data-testid={testId}
          // The panel says what it is in two words and describes nothing
          // further; without this Radix warns about the description it
          // cannot find.
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // The last moment at which the element the operator was on
            // is still the focused one.
            event.preventDefault()
            restoreFocusTo.current =
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null
            const wanted = focusRef?.current ?? null
            if (wanted !== null) wanted.focus()
            else panel.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            event.preventDefault()
            restoreFocusTo.current?.focus()
            restoreFocusTo.current = null
          }}
          className={`text-body fixed z-50 flex flex-col overflow-hidden rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-surface)] text-foreground shadow-[var(--shadow-lg)] ${PLACEMENTS[placement]} ${width}`}
        >
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/**
 * The header strip: the kicker that names the overlay and is its
 * accessible name, a gloss beside it, and the hint on the right.
 */
export function OverlayHeader({
  title,
  gloss,
  hint,
  children,
}: {
  title: string
  /** What this instance of the overlay is about, or nothing. */
  gloss?: ReactNode
  /** The right-hand reminder, `esc close` in most of them. */
  hint: string
  /** Anything drawn between the gloss and the hint — a status pill. */
  children?: ReactNode
}) {
  return (
    <div className="flex flex-none items-center gap-[10px] border-b border-[var(--color-neutral-900)] px-[14px] py-[10px]">
      <Dialog.Title className="text-kicker whitespace-nowrap text-[var(--color-accent-300)]">
        {title}
      </Dialog.Title>
      {gloss !== undefined && (
        <span
          data-testid="overlay-gloss"
          className="text-hint truncate text-[var(--color-neutral-500)]"
        >
          {gloss}
        </span>
      )}
      <div className="flex-1" />
      {children}
      <span className="text-hint whitespace-nowrap text-muted-foreground">{hint}</span>
    </div>
  )
}
