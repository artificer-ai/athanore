/**
 * The detail region on the right: the pane bar and the pane's scrolling
 * body (`docs/v1/10-frontend.md` §Layout).
 *
 * The panes themselves are the pane host's (T062) and come from the
 * plugin manifest, so the bar here carries only what the shell owns: the
 * cycle controls and the selected run's id from `?run=`. `◀`/`▶` are
 * disabled while there is no pane list to cycle — the shell will not
 * pretend to a pane count it does not have.
 *
 * The bar opens with the mock's `❮`, which collapses the run list to the
 * rail `Splitter` draws in its place; collapsed, the rail's own `❯` is
 * the way back, so the two are never on screen together.
 */
import type { AppSearch } from '../routes/search'
import { usePrefs } from '../store/prefs'
import { useUi } from '../store/ui'

export function Detail({ search }: { search: AppSearch }) {
  const focused = useUi((s) => s.focus === 'detail')
  const setFocus = useUi((s) => s.setFocus)
  const listCollapsed = usePrefs((s) => s.listCollapsed)
  const setListCollapsed = usePrefs((s) => s.setListCollapsed)

  return (
    <section
      aria-label="detail"
      data-region="detail"
      data-focused={focused}
      onMouseDown={() => setFocus('detail')}
      onFocusCapture={() => setFocus('detail')}
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col"
    >
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
          disabled
          aria-label="previous pane"
          className="text-body px-[4px] text-[var(--color-accent-400)] disabled:text-[var(--color-neutral-700)]"
        >
          ◀
        </button>
        <span
          data-testid="pane-label"
          className="text-meta font-medium whitespace-nowrap tracking-[0.08em] text-[var(--color-accent-300)]"
        >
          {/* The pane cycle is read from the manifest in T062. */}—
        </span>
        <button
          type="button"
          disabled
          aria-label="next pane"
          className="text-body px-[4px] text-[var(--color-accent-400)] disabled:text-[var(--color-neutral-700)]"
        >
          ▶
        </button>

        <div className="flex-1" />

        {search.run !== undefined && (
          <>
            <span className="text-hint text-muted-foreground">run</span>
            <span
              data-testid="selected-run"
              className="text-meta text-[var(--color-neutral-400)]"
            >
              {search.run}
            </span>
          </>
        )}
      </div>

      {/* Pane content arrives with the pane host in T062. */}
      <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto" />
    </section>
  )
}
