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
 *
 * Below the breakpoint that slot holds a back control instead (21
 * §Narrow layout): there is no split to collapse, and the detail is
 * standing where the run list was, so `←` clearing `?run=` is the way
 * back to it. The `◀`/`▶` buttons and the dots stay — they are the touch
 * route through the pane cycle — and grow to the 24×24 px hit area WCAG
 * 2.5.8 asks of a touch target, the dots by way of a transparent box
 * around the 14×3 px bar rather than by drawing a bigger bar.
 *
 * On the **narrow global screen** (D216) the bar is over the global
 * cycle and `leave` is given: the left slot draws one control, `←`,
 * labelled `back to the run` — the screen is always over a run (D217),
 * so the slot has one label — and neither the selection's back control
 * nor the collapse toggle beside it, the screen being narrow-only and
 * `panes.run` `undefined` there anyway. The right slot stays gated on
 * `panes.runId` and so draws nothing, exactly as the desktop's global
 * view does. The dots need no new colour: run panes and global panes
 * are never in one row, and the inbox is a builtin (neutral-800) while
 * a plugin's global pane is a plugin's (accent-800), the same mapping
 * as everywhere.
 */
import { RadioGroup } from 'radix-ui'

import { statusTone, StatusPill } from '../components/RunList'
import { useIsNarrow } from '../lib/useIsNarrow'
import { cn } from '../lib/utils'
import { usePrefs } from '../store/prefs'
import type { PaneModel } from './usePanes'

/** The touch target of WCAG 2.5.8, on the controls narrow chrome has. */
const TOUCH = 'max-md:min-h-[24px] max-md:min-w-[24px]'

/** The classes the left slot's `←` carries, whichever way it goes. */
const BACK =
  'text-hint flex items-center justify-center rounded-lg border border-border px-[6px] py-px text-muted-foreground hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)]'

export function PaneBar({
  panes,
  onBack,
  leave,
}: {
  panes: PaneModel
  /**
   * Clear `?run=`: the back control's whole action, at every width.
   *
   * Narrow, it is 21 §Narrow layout's back arrow and the list is what
   * you go back *to*. Wide, the list is already on screen, so it is not
   * navigation but deselection — and it is the only pointer route to the
   * `global` panes, which are shown when no run is selected and were
   * otherwise unreachable once one had been (D209).
   *
   * Absent only when a run is not selected, or in a shell that passes no
   * handler.
   */
  onBack?: (() => void) | undefined
  /**
   * Given while the bar is over the narrow global screen: the left slot
   * is then that screen's `←` alone, and this puts the screen away —
   * `?global=` cleared, the run under it untouched (D216, D217).
   */
  leave?: (() => void) | undefined
}) {
  const listCollapsed = usePrefs((s) => s.listCollapsed)
  const setListCollapsed = usePrefs((s) => s.setListCollapsed)
  const narrow = useIsNarrow()
  const run = panes.run
  const empty = panes.panes.length === 0

  return (
    <div className="bg-chrome flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-border px-[12px] py-[6px]">
      {/* Back, whenever there is a selection to clear. Its own control
          rather than a mode of the collapse toggle: wide, both are
          useful at once — hide the list, and stop looking at this run
          are different wishes. */}
      {leave !== undefined ? (
        // The global screen's own `←`: it clears `?global=` and nothing
        // else, so the run — and the pane of it — under the screen is
        // where it lands (D216, D217).
        <button
          type="button"
          onClick={leave}
          aria-label="back to the run"
          title="back to the run (esc)"
          className={`${BACK} ${TOUCH}`}
        >
          ←
        </button>
      ) : (
        onBack !== undefined &&
        run !== undefined && (
          <button
            type="button"
            onClick={onBack}
            aria-label={narrow ? 'back to runs' : 'clear the selected run'}
            title={narrow ? 'back to runs' : 'clear the selected run (esc)'}
            className={`${BACK} ${TOUCH}`}
          >
            ←
          </button>
        )
      )}
      {leave === undefined && !narrow && !listCollapsed && (
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
        className={`text-body px-[4px] text-[var(--color-accent-400)] hover:text-[var(--color-accent-200)] disabled:text-[var(--color-neutral-700)] ${TOUCH}`}
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
        className={`text-body px-[4px] text-[var(--color-accent-400)] hover:text-[var(--color-accent-200)] disabled:text-[var(--color-neutral-700)] ${TOUCH}`}
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
        {panes.panes.map((pane, index) => {
          // The mock's colours: accent for the current pane, accent-800
          // for a plugin's, neutral-800 for a builtin's.
          const colour =
            index === panes.index
              ? 'bg-[var(--color-accent)]'
              : pane.builtin
                ? 'bg-[var(--color-neutral-800)]'
                : 'bg-[var(--color-accent-800)]'
          return (
            <RadioGroup.Item
              key={pane.id}
              value={String(index)}
              title={pane.name}
              aria-label={pane.name}
              data-pane={pane.name}
              data-builtin={pane.builtin}
              className={cn(
                'h-[3px] w-[14px] rounded-lg',
                colour,
                // Narrow, the item *is* the hit area and the bar inside
                // it is the mark: 3 px of height is not something a
                // finger can find (WCAG 2.5.8).
                'max-md:flex max-md:h-[24px] max-md:w-[24px] max-md:items-center max-md:justify-center max-md:bg-transparent',
              )}
            >
              <span
                aria-hidden
                className={cn('hidden h-[3px] w-[14px] rounded-lg max-md:block', colour)}
              />
            </RadioGroup.Item>
          )
        })}
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
