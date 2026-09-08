/**
 * The detail region on the right: the pane bar and the pane's scrolling
 * body (`docs/v1/10-frontend.md` §Layout).
 *
 * It owns neither the bar nor the cycle. The bar is `panes/PaneBar` and
 * which panes there are comes from the manifest through `usePanes`, so
 * this file is the bar over a body, plus what to show when the cycle is
 * empty. Drawing a pane's contents is `PaneRenderer`'s (T062a).
 *
 * An empty cycle is a real state, not an error: a server with no
 * workflows registered still carries the builtins (09 §Mounting), but a
 * selection with no run and a build whose only `global` pane is the
 * inbox will have one pane, and the manifest is a request that can still
 * be in flight. Each of those reads differently and says so.
 */
import { PaneBar } from '../panes/PaneBar'
import type { PaneModel } from '../panes/usePanes'
import { useUi } from '../store/ui'

export function Detail({ panes }: { panes: PaneModel }) {
  const focused = useUi((s) => s.focus === 'detail')
  const setFocus = useUi((s) => s.setFocus)

  return (
    <section
      aria-label="detail"
      data-region="detail"
      data-focused={focused}
      onMouseDown={() => setFocus('detail')}
      onFocusCapture={() => setFocus('detail')}
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col"
    >
      <PaneBar panes={panes} />

      {/* The panel itself is drawn by `PaneRenderer` in T062a; what the
          host owns is the three states in which there is no panel to
          draw. */}
      <div
        data-testid="pane-body"
        data-pane={panes.current?.id}
        className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto"
      >
        {panes.current === undefined && (
          <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
            {panes.isPending
              ? 'loading panes…'
              : panes.runId === undefined
                ? 'no run selected'
                : 'this run has no panes'}
          </p>
        )}
      </div>
    </section>
  )
}
