/**
 * `kv`: an object, as the mock's two-column description list (09 §Panel
 * kinds, 10 §Panes — the overview's meta grid is the same grid).
 *
 * A `dl` rather than a table because that is what it is: each key is a
 * term and each value its description, which is the pairing a screen
 * reader announces and a table would not.
 *
 * Key order is the object's own — JSON preserves the order the source
 * wrote, and a plugin that put STATUS before AGE meant to.
 */
import { formatValue } from './format'

export function KvPane({ data }: { data: Record<string, unknown> }) {
  const entries = Object.entries(data)
  if (entries.length === 0) {
    return (
      <p className="text-row text-muted-foreground" role="status">
        nothing to show
      </p>
    )
  }

  return (
    <dl
      data-testid="pane-kv"
      className="grid grid-cols-[repeat(auto-fit,minmax(240px,1fr))] gap-x-[22px] gap-y-[10px]"
    >
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="grid grid-cols-[minmax(0,86px)_minmax(0,1fr)] items-start gap-[10px]"
        >
          <dt className="text-hint pt-px tracking-[0.1em] text-muted-foreground">
            {key}
          </dt>
          <dd className="text-body [overflow-wrap:anywhere] text-[var(--color-neutral-300)]">
            {formatValue(value)}
          </dd>
        </div>
      ))}
    </dl>
  )
}
