/**
 * The requests pane: everything this run has asked a person, what they
 * said, and — from T064 — the controls that say it
 * (`docs/v1/10-frontend.md` §Panes item 4, `docs/v1/06-requests.md`
 * §Surfaces, and the mock's `isMessages` block in
 * `docs/v1/design/Athanore.dc.html`).
 *
 * It is the mock's `messages` pane re-purposed (15, D33). Athanore has
 * no node-to-node messages — the work log is the inter-node channel — so
 * what the pane draws is the human-in-the-loop history: one card per
 * request, `node → operator` or `agent → operator`, the timestamp, the
 * prompt, and then either the answer or the controls that give one.
 *
 * **Pending first.** The rest keep the order the route sent, which is
 * the order they were asked (`./requests.ts`): the questions an operator
 * can still act on are the reason to open the pane, and everything under
 * them is a history, which reads forwards.
 *
 * **The card is shared with the inbox.** `components/RequestCard.tsx`
 * draws it and `components/RequestPanel.tsx` answers it — the same panel
 * that docks under the agent stream — because "answerable in place" (06
 * §SPA) has to mean the same three controls wherever a request is drawn.
 *
 * The pane reads `GET /api/runs/{id}/requests` (08 §Runs) through the
 * generated query, so its cache entry is the one `request.*` invalidates
 * (10 §Realtime and caching) and a new question appears without a poll.
 * With no run selected there is nothing here to scope to, and what the
 * same element draws instead is the inbox: every open request across
 * runs, newest first (06 §SPA).
 */
import { Inbox } from '../../components/Inbox'
import { RequestCard } from '../../components/RequestCard'
import { cn } from '../../lib/utils'
import { ErrorCard } from './cards'
import {
  orderRequests,
  pendingCount,
  requestsError,
  useRunRequests,
} from './requests'

/** The glyph a request waiting on a person carries, as the run list. */
const PENDING_GLYPH = '⚠'

/** The mock's header separator: a neutral-800 pipe between the parts. */
function Bar() {
  return <span className="text-[var(--color-neutral-800)]">│</span>
}

/** A status line: what the pane is waiting for, or has nothing of. */
function Status({ children }: { children: string }) {
  return (
    <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
      {children}
    </p>
  )
}

export function Requests({ runId }: { runId: string | undefined }) {
  // The `global` twin of this pane is the inbox (06 §SPA). It is the
  // same element in the manifest and a different list, so the branch is
  // here and the header below belongs to the run's pane alone.
  if (runId === undefined) return <Inbox />
  return <RunRequests runId={runId} />
}

/** The requests of one run: the pane with a selection behind it. */
function RunRequests({ runId }: { runId: string }) {
  const { data, isError, error } = useRunRequests(runId)

  const requests = data ?? []
  const open = pendingCount(requests)

  return (
    <div data-testid="pane-requests" className="flex min-h-0 flex-1 flex-col">
      <div className="text-hint flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-900)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span>REQUESTS</span>
        {data !== undefined && (
          <>
            <Bar />
            <span data-testid="request-count">{requests.length} asked</span>
            <div className="flex-1" />
            <span
              data-testid="request-open"
              className={cn(
                'whitespace-nowrap',
                open > 0 ? 'text-status-gate' : 'text-[var(--color-neutral-500)]',
              )}
            >
              {open > 0 ? `${PENDING_GLYPH} ${String(open)} open` : '○ none open'}
            </span>
          </>
        )}
      </div>

      {isError ? (
        // The pane makes its own request, so a refusal is named here
        // rather than left to look like a run that asked nothing.
        <div className="p-[12px_14px]">
          <ErrorCard
            {...requestsError(error)}
            source={`/api/runs/${runId}/requests`}
          />
        </div>
      ) : data === undefined ? (
        <Status>loading the requests…</Status>
      ) : requests.length === 0 ? (
        <Status>this run has asked you nothing</Status>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-[8px] overflow-x-hidden overflow-y-auto px-[14px] pt-[12px] pb-[24px]">
          {orderRequests(requests).map((request) => (
            <RequestCard key={request.id} request={request} />
          ))}
        </div>
      )}
    </div>
  )
}
