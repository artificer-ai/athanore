/**
 * The run list on the left (`docs/v1/10-frontend.md` §Layout).
 *
 * The rows themselves are T061's: this is the frame — the column header,
 * the scrolling body, and the footer strip. `count` is the number of rows
 * on screen, which is what the footer strip reports. The 30 px rail it
 * collapses to is T058a's.
 */
import { useUi } from '../store/ui'

/** The mock's column template, to the pixel. */
const COLUMNS =
  'minmax(0, 108px) minmax(0, 104px) minmax(110px, 1fr) minmax(0, 84px) minmax(0, 92px) 46px'

const HEADINGS = ['RUN', 'WORKFLOW', 'TITLE', 'STATUS', 'NODE', 'AGE']

export function RunList({ count }: { count: number }) {
  const focused = useUi((s) => s.focus === 'list')
  const setFocus = useUi((s) => s.setFocus)

  return (
    <section
      aria-label="runs"
      data-region="list"
      data-focused={focused}
      onMouseDown={() => setFocus('list')}
      onFocusCapture={() => setFocus('list')}
      className="flex h-full min-h-0 min-w-0 flex-col border-r border-border data-[focused=true]:border-r-[var(--color-accent-800)]"
    >
      <div
        role="row"
        className="text-hint bg-chrome grid gap-[8px] overflow-hidden border-b border-border px-[12px] py-[6px] tracking-[0.1em] text-muted-foreground"
        style={{ gridTemplateColumns: COLUMNS }}
      >
        {HEADINGS.map((heading) => (
          <span key={heading} className={heading === 'AGE' ? 'text-right' : undefined}>
            {heading}
          </span>
        ))}
      </div>

      {/* Rows arrive with the `GET /api/runs` query in T061. */}
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto" />

      <div className="text-hint bg-chrome flex gap-[14px] border-t border-border px-[12px] py-[5px] text-muted-foreground">
        <span data-testid="rows-shown">{count} shown</span>
        <span>↑↓ select</span>
        <span>⏎ focus detail</span>
      </div>
    </section>
  )
}
