/**
 * One pane, drawn from its manifest entry and the data its `source`
 * answered with.
 *
 * This is the component that makes the plugin system visible: the host
 * knows a panel's `kind`, its `source` and its scope, and nothing else
 * about it. Everything below the pane bar came off the wire.
 *
 * What one panel draws is `./content.tsx` — shared with the cards
 * appended to the overview (`./PanelCards.tsx`), which are panels drawn
 * in a frame instead of in a pane. This file is the pane around it: the
 * header, the footer a plugin's pane carries, and the scroller the kinds
 * that do not bring their own are poured into.
 */
import { PanelCards } from './PanelCards'
import { paneContent } from './content'
import { PaneSection } from './kinds'
import { panelParams, usePanelSource, type PanelScope } from './source'
import type { Pane } from './usePanes'

/** The pane's own header: what it is, and where its data comes from. */
function PaneHeader({ pane }: { pane: Pane }) {
  return (
    <div className="text-hint flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-900)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
      {!pane.builtin && (
        <>
          <span className="text-[var(--color-accent-300)]">PLUGIN</span>
          <span className="text-[var(--color-neutral-800)]">│</span>
        </>
      )}
      <span data-testid="pane-title" className="text-[var(--color-neutral-400)]">
        {pane.name}
      </span>
      <div className="flex-1" />
      {pane.panel.source != null && (
        <span data-testid="pane-source" className="whitespace-nowrap">
          {pane.panel.source}
        </span>
      )}
    </div>
  )
}

/** 10 §Panes' footer line, on the panes a workflow contributed. */
function PaneFooter({ workflow }: { workflow: string }) {
  return (
    <p className="text-kicker flex-none px-[14px] pb-[16px] normal-case text-muted-foreground">
      registered by {workflow} · panes are contributed with @wf.panel(...)
    </p>
  )
}

export function PaneRenderer({
  pane,
  scope,
  node,
  onOpenTask,
  onFilterNode,
  onOpenNode,
  onOpenLibrary,
}: {
  pane: Pane
  scope: PanelScope
  /** `?node=`: the node the event log is filtered to (10 §Panes). */
  node?: string | undefined
  /** Open an attempt in the task drawer; the overview's rows use it. */
  onOpenTask?: ((taskId: number) => void) | undefined
  /** Write `?node=`; the log pane's filter clears itself with it. */
  onFilterNode?: ((node: string | undefined) => void) | undefined
  /** Jump to the log pane filtered to a node; the graph's rows use it. */
  onOpenNode?: ((node: string) => void) | undefined
  /** Open the workflow library; the graph's `open definition` uses it. */
  onOpenLibrary?: (() => void) | undefined
}) {
  const params = panelParams(pane.panel, scope)
  const query = usePanelSource(pane.panel, params)

  // The cards are made here and placed by the overview, which is the
  // one pane that takes them (09 §Slots): every other kind ignores them,
  // and an element nothing mounts costs nothing.
  const content = paneContent(pane, params, query, {
    scope,
    node,
    onOpenTask,
    onFilterNode,
    onOpenNode,
    onOpenLibrary,
    cards: <PanelCards scope={scope} onOpenTask={onOpenTask} />,
  })

  const footer = pane.builtin ? null : <PaneFooter workflow={pane.workflow} />

  return (
    <div
      data-testid="pane-renderer"
      data-kind={pane.panel.kind}
      className="flex min-h-0 flex-1 flex-col"
    >
      <PaneHeader pane={pane} />
      {content.scrolls ? (
        <>
          {content.node}
          {footer}
        </>
      ) : (
        <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
          <PaneSection>{content.node}</PaneSection>
          {footer}
        </div>
      )}
    </div>
  )
}
