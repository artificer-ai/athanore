/**
 * The detail region on the right: the pane bar and the pane's scrolling
 * body (`docs/v1/10-frontend.md` §Layout).
 *
 * It owns neither the bar nor the cycle nor the pane. The bar is
 * `panes/PaneBar`, which panes there are comes from the manifest through
 * `usePanes`, and what one looks like is `panes/PaneRenderer` — so this
 * file is the bar over a body, plus what to show when the cycle is
 * empty.
 *
 * An empty cycle is a real state, not an error: a server with no
 * workflows registered still carries the builtins (09 §Mounting), but a
 * selection with no run and a build whose only `global` pane is the
 * inbox will have one pane, and the manifest is a request that can still
 * be in flight. Each of those reads differently and says so.
 *
 * The region takes focus itself when `⏎` hands it the keyboard (10
 * §Keyboard), which is what `ref` and `tabIndex={-1}` are for: the
 * shell holds the reference because the shell is where the key is bound.
 *
 * The body does not scroll: the pane does. A `log` pane virtualises, and
 * a viewport that grows with its content is not one a virtualiser can
 * measure, so `PaneRenderer` is given the height and decides what to do
 * with it (10 §Panes).
 */
import type { Ref } from 'react'

import { PaneBar } from '../panes/PaneBar'
import { PaneRenderer } from '../panes/PaneRenderer'
import type { PaneModel } from '../panes/usePanes'
import { useUi } from '../store/ui'

export function Detail({
  ref,
  panes,
  taskId,
  node,
  onOpenTask,
  onFilterNode,
  onOpenNode,
  onOpenLibrary,
}: {
  /**
   * The region itself, so that `⏎` can hand it the keyboard (T067). It
   * is a plain prop because React 19 passes `ref` as one.
   */
  ref?: Ref<HTMLElement> | undefined
  panes: PaneModel
  /** The focused attempt, from `?task=`: a `task`-scoped panel's id. */
  taskId?: number | undefined
  /** `?node=`: the node the event log is filtered to (10 §Panes). */
  node?: string | undefined
  /** Open an attempt in the task drawer: the overview's NODES rows. */
  onOpenTask?: ((taskId: number) => void) | undefined
  /** Write `?node=`: the graph pane sets it, the log pane clears it. */
  onFilterNode?: ((node: string | undefined) => void) | undefined
  /** Jump to the log pane filtered to a node: the graph pane's rows. */
  onOpenNode?: ((node: string) => void) | undefined
  /** Open the workflow library: the graph pane's `open definition`. */
  onOpenLibrary?: (() => void) | undefined
}) {
  const focused = useUi((s) => s.focus === 'detail')
  const setFocus = useUi((s) => s.setFocus)

  return (
    <section
      ref={ref}
      aria-label="detail"
      data-region="detail"
      data-focused={focused}
      // Focusable programmatically and not by `tab`: `⏎` focus detail
      // moves the keyboard here (10 §Keyboard), and the region is a
      // container rather than a control, so it is not a tab stop.
      tabIndex={-1}
      onMouseDown={() => setFocus('detail')}
      onFocusCapture={() => setFocus('detail')}
      className="flex h-full min-h-0 min-w-0 flex-1 flex-col focus:outline-none"
    >
      <PaneBar panes={panes} />

      {/* The panel is `PaneRenderer`'s; what the host owns is the three
          states in which there is no panel to draw. */}
      <div
        data-testid="pane-body"
        data-pane={panes.current?.id}
        className="flex min-h-0 flex-1 flex-col"
      >
        {panes.current === undefined ? (
          <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
            {panes.isPending
              ? 'loading panes…'
              : panes.runId === undefined
                ? 'no run selected'
                : 'this run has no panes'}
          </p>
        ) : (
          <PaneRenderer
            // Remounted per pane: a pane's state — a table's sort, a
            // log's tailing — belongs to that pane and not to the slot
            // the cycle draws it in.
            key={panes.current.id}
            pane={panes.current}
            scope={{ runId: panes.runId, taskId }}
            node={node}
            onOpenTask={onOpenTask}
            onFilterNode={onFilterNode}
            onOpenNode={onOpenNode}
            onOpenLibrary={onOpenLibrary}
          />
        )}
      </div>
    </section>
  )
}
