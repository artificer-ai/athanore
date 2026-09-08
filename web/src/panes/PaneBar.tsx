/**
 * The detail region's bar: the collapse toggle, `◀ PANE (i/n) ▶`, the
 * pane dots, and the selected run's id and status pill (10 §Layout).
 *
 * The dots are a `RadioGroup` styled as 14×3 px bars, which is 10
 * §Components' mapping and not decoration: they are a single-choice
 * control over the pane cycle, so Radix gives them roving focus, arrow
 * keys and the `aria-checked` a screen reader needs — none of which a
 * row of `<button>`s would have. Their colours are the mock's: accent
 * for the current pane, accent-800 for a plugin's, neutral-800 for a
 * builtin's, so an operator can see at a glance which panes came from
 * the workflow they are running.
 *
 * The bar opens with the mock's `❮`, which collapses the run list to the
 * rail `Splitter` draws in its place; collapsed, the rail's own `❯` is
 * the way back, so the two are never on screen together.
 */
import { RadioGroup } from 'radix-ui'

import { statusTone, StatusPill } from '../components/RunList'
import { cn } from '../lib/utils'
import { usePrefs } from '../store/prefs'
import type { PaneModel } from './usePanes'

export function PaneBar({ panes }: { panes: PaneModel }) {
  const listCollapsed = usePrefs((s) => s.listCollapsed)
  const setListCollapsed = usePrefs((s) => s.setListCollapsed)
  const run = panes.run
  const empty = panes.panes.length === 0

  return (
    <div className="bg-chrome flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-border px-[12px] py-[6px]">
      {!listCollapsed && (
        <button
          type="button"
          onClick={() => setListCollapsed(true)}
          aria-label="hide run list"
          title="hide run list (b)"
          className="text-hint rounded-lg border border-border px-[6px] py-px text-muted-foreground hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)]"
        >
          ❮
        </button>
      )}

      <button
        type="button"
        disabled={empty}
        onClick={panes.prev}
        aria-label="previous pane"
        className="text-body px-[4px] text-[var(--color-accent-400)] hover:text-[var(--color-accent-200)] disabled:text-[var(--color-neutral-700)]"
      >
        ◀
      </button>
      <span
        data-testid="pane-label"
        className="text-meta font-medium whitespace-nowrap tracking-[0.08em] text-[var(--color-accent-300)]"
      >
        {panes.label}
      </span>
      <button
        type="button"
        disabled={empty}
        onClick={panes.next}
        aria-label="next pane"
        className="text-body px-[4px] text-[var(--color-accent-400)] hover:text-[var(--color-accent-200)] disabled:text-[var(--color-neutral-700)]"
      >
        ▶
      </button>

      <RadioGroup.Root
        aria-label="panes"
        orientation="horizontal"
        value={empty ? '' : String(panes.index)}
        onValueChange={(value) => panes.jump(Number(value))}
        className="ml-[4px] flex gap-[4px]"
      >
        {panes.panes.map((pane, index) => (
          <RadioGroup.Item
            key={pane.id}
            value={String(index)}
            title={pane.name}
            aria-label={pane.name}
            data-pane={pane.name}
            data-builtin={pane.builtin}
            className={cn(
              'h-[3px] w-[14px] rounded-lg',
              index === panes.index
                ? 'bg-[var(--color-accent)]'
                : pane.builtin
                  ? 'bg-[var(--color-neutral-800)]'
                  : 'bg-[var(--color-accent-800)]',
            )}
          />
        ))}
      </RadioGroup.Root>

      <div className="flex-1" />

      {panes.runId !== undefined && (
        <>
          <span className="text-hint text-muted-foreground">run</span>
          <span
            data-testid="selected-run"
            className="text-meta text-[var(--color-neutral-400)]"
          >
            {panes.runId}
          </span>
          {/* The pill waits for the row: a status is a fact about the
              run, and `?run=` alone is not one (01 §Real data only). */}
          {run !== undefined && (
            <StatusPill
              status={run.status}
              tone={statusTone(run.status, run.pending_requests ?? 0)}
            />
          )}
        </>
      )}
    </div>
  )
}
