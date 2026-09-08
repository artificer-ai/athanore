/**
 * The two cards a pane falls back to, and the section frame the kinds
 * are drawn in.
 *
 * Both cards are load-bearing rather than decoration. 09 §Panel kinds
 * ends with "Unknown `kind` renders a placeholder card, never a crash":
 * a plugin built against a later version of Athanore declares kinds this
 * build has no renderer for, and the pane host must degrade to a card
 * naming what it cannot draw. {@link ErrorCard} is the same promise on
 * the other side of the request — a `source` that answered 500 is the
 * plugin's failure, not the operator's, and the pane says which panel
 * and which URL rather than going blank.
 */
import type { ReactNode } from 'react'

/** The padded body every kind is drawn in (the mock's `12px 14px`). */
export function PaneSection({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col gap-[14px] px-[14px] pt-[12px] pb-[20px]">
      {children}
    </div>
  )
}

/**
 * What this build cannot draw, said plainly.
 *
 * `detail` is the fact that makes the card useful: the kind's name, the
 * element tag, or the action a form was declared for. Without it the
 * card is an apology; with it, it is the answer to "why is this pane
 * empty".
 */
export function PlaceholderCard({
  title,
  detail,
}: {
  title: string
  detail?: ReactNode
}) {
  return (
    <div
      role="note"
      data-testid="pane-placeholder"
      className="rounded-lg border border-border bg-card px-[12px] py-[10px]"
    >
      <p className="text-row text-[var(--color-neutral-300)]">{title}</p>
      {detail !== undefined && (
        <p className="text-meta mt-[4px] text-muted-foreground">{detail}</p>
      )}
    </div>
  )
}

/** A `source` that refused, with the status and the URL that refused. */
export function ErrorCard({
  message,
  status,
  code,
  source,
}: {
  message: string
  status?: number | undefined
  code?: string | undefined
  source?: string | undefined
}) {
  return (
    <div
      role="alert"
      data-testid="pane-error"
      className="rounded-lg border border-status-fail bg-card px-[12px] py-[10px]"
    >
      <p className="text-row text-status-fail">
        {status === undefined
          ? 'this panel failed to load'
          : `${String(status)} · this panel failed to load`}
      </p>
      <p className="text-meta mt-[4px] text-[var(--color-neutral-300)]">{message}</p>
      {(code !== undefined || source !== undefined) && (
        <p className="text-meta mt-[4px] break-all text-muted-foreground">
          {[code, source].filter((part) => part !== undefined).join(' · ')}
        </p>
      )}
    </div>
  )
}
