/**
 * The `placement="card"` panels of the selected run, drawn as cards
 * under the overview pane (`docs/v1/09-plugins.md` §Slots — a `run`
 * panel is "a pane in the selected run's cycle … or a card appended to
 * the overview pane"; 15, D163).
 *
 * A card is a panel like any other: it declares a `kind` and a `source`,
 * it is fetched and narrowed the same way, and it draws through the same
 * dispatch (`./content.tsx`). Only the frame around it differs, and the
 * frame carries the two facts a pane carries in its bar and its footer —
 * the panel's name, and the workflow that registered it.
 *
 * They are made here and *placed* by the overview, which is handed them
 * as `cards`. The other way round would have the renderer of the cards
 * importing the pane that contains them and the pane importing the
 * renderer, which is a cycle for no gain.
 */
import { paneContent, type RenderContext } from './content'
import { panelParams, usePanelSource, type PanelScope } from './source'
import { useCards, type Pane } from './usePanes'

/**
 * How tall a card whose kind brings its own scroller is drawn.
 *
 * A `log` card virtualises, and a virtualiser measures its viewport: a
 * card that grew with its content would leave it measuring one that
 * never ends (the same reason `PaneRenderer` hands the pane's height to
 * a scrolling kind rather than wrapping it).
 */
const SCROLLING_CARD_HEIGHT = 'flex h-[280px] min-h-0 flex-col'

/** One card: the panel's frame, and whatever its kind draws inside it. */
function PanelCard({ pane, ctx }: { pane: Pane; ctx: RenderContext }) {
  const params = panelParams(pane.panel, ctx.scope)
  const query = usePanelSource(pane.panel, params)
  const content = paneContent(pane, params, query, ctx)

  return (
    <div
      data-testid="panel-card"
      data-panel={pane.id}
      className="overflow-hidden rounded-lg border border-[var(--color-neutral-900)] bg-card"
    >
      <div className="text-hint flex flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-900)] px-[12px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span className="text-[var(--color-neutral-400)]">{pane.name}</span>
        {!pane.builtin && (
          <>
            <span className="text-[var(--color-neutral-800)]">│</span>
            <span>{pane.workflow}</span>
          </>
        )}
      </div>
      <div
        className={content.scrolls ? SCROLLING_CARD_HEIGHT : 'px-[12px] py-[10px]'}
      >
        {content.node}
      </div>
    </div>
  )
}

export function PanelCards({
  scope,
  onOpenTask,
}: {
  scope: PanelScope
  onOpenTask?: ((taskId: number) => void) | undefined
}) {
  const cards = useCards(scope.runId)
  if (cards.length === 0) return null

  return (
    <section
      aria-label="panels"
      data-testid="overview-cards"
      className="flex flex-col gap-[14px] border-b border-[var(--color-neutral-900)] px-[14px] py-[12px] last:border-b-0"
    >
      {cards.map((card) => (
        <PanelCard key={card.id} pane={card} ctx={{ scope, onOpenTask }} />
      ))}
    </section>
  )
}
