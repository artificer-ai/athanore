/**
 * The detail region on the right: the pane bar and the pane's scrolling
 * body.
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
 * The region follows the browser's focus and nothing else moves it:
 * `tab` is how attention reaches it (10 §Keyboard, D176 (1), D204 (1)).
 *
 * The body does not scroll: the pane does. A `log` pane virtualises, and
 * a viewport that grows with its content is not one a virtualiser can
 * measure, so `PaneRenderer` is given the height and decides what to do
 * with it (10 §Panes).
 */
import { PaneBar } from '../panes/PaneBar'
import { PaneRenderer } from '../panes/PaneRenderer'
import type { PaneModel } from '../panes/usePanes'
import { useUi } from '../store/ui'

export function Detail({
  panes,
  taskId,
  node,
  onOpenTask,
  onFilterNode,
  onOpenNode,
  onOpenLibrary,
  onBack,
  leave,
}: {
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
  /**
   * Clear `?run=`: the pane bar's back control, below the breakpoint
   * (21 §Narrow layout). It is passed through rather than acted on
   * here, because the bar is where the left slot is.
   */
  onBack?: (() => void) | undefined
  /**
   * The narrow global screen's way back (21 §Regions, narrow, D216,
   * D218): given while this detail is drawn over the global cycle below
   * the breakpoint, and handed to the bar unchanged for the same reason
   * `onBack` is. The empty-cycle copy below is right there too — `no
   * run selected` means the manifest answered with no global pane at
   * all, which no build with the builtins has.
   */
  leave?: (() => void) | undefined
}) {
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
      <PaneBar panes={panes} onBack={onBack} leave={leave} />

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
