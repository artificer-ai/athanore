/**
 * The requests pane: everything this run has asked a person, and what
 * they said (`docs/v1/10-frontend.md` §Panes item 4,
 * `docs/v1/06-requests.md` §Surfaces, and the mock's `isMessages` block
 * in `docs/v1/design/Athanore.dc.html`).
 *
 * It is the mock's `messages` pane re-purposed (15, D33). Athanore has
 * no node-to-node messages — the work log is the inter-node channel — so
 * what the pane draws is the human-in-the-loop history: one card per
 * request, `node → operator` or `agent → operator`, the timestamp, the
 * prompt, and then either the answer or the space the controls that give
 * one will occupy.
 *
 * **Pending first.** The rest keep the order the route sent, which is
 * the order they were asked (`./requests.ts`): the questions an operator
 * can still act on are the reason to open the pane, and everything under
 * them is a history, which reads forwards.
 *
 * **It renders the controls slot; it does not render controls.** T064
 * adds the docked panel and the `ActionForm` that answer a request, and
 * the same components will fill this slot. What is here now is what the
 * card can say without them: the shape of answer the request is waiting
 * for, and — for an `options` request — the choices it offers, drawn as
 * labels rather than as buttons, because a button that did nothing would
 * be worse than no button.
 *
 * **A permission carries the tool call.** `tool_call` is the bounded
 * summary `athanore/agents/policies.py` stores when it asks: the title,
 * the ACP kind and the raw input, which together are what an operator
 * decides on. This pane bounds it again on the way out, for the reason
 * `TOOL_CALL_CHARS` gives.
 *
 * **The answer's author is drawn, always.** A permission that timed out
 * is answered by `engine` under `permission_timeout_action` (06
 * §Timeouts), and an operator reading back through a run wants to know
 * which answers were theirs and which the clock's.
 *
 * The pane reads `GET /api/runs/{id}/requests` (08 §Runs) through the
 * generated query, so its cache entry is the one `request.*` invalidates
 * (10 §Realtime and caching) and a new question appears without a poll.
 * With no run selected there is nothing here to scope to: the inbox that
 * replaces this pane then — every open request across runs, newest first
 * (06 §SPA) — is T064's, and until it exists the pane says which
 * selection it is waiting for rather than showing an empty list.
 */
import { useQuery } from '@tanstack/react-query'

import { getRequestsApiRunsRunIdRequestsGetOptions } from '../../api/gen/@tanstack/react-query.gen'
import type { RequestOption, RequestView } from '../../api/gen/types.gen'
import { cn } from '../../lib/utils'
import { ErrorCard, PlaceholderCard } from './cards'
import { rowTime } from './format'
import {
  answerText,
  awaiting,
  orderRequests,
  pendingCount,
  requestState,
  requestsError,
  toolCallSummary,
  TOOL_CALL_CHARS,
} from './requests'

/** The glyph a request waiting on a person carries, as the run list. */
const PENDING_GLYPH = '⚠'

/** The mock's header separator: a neutral-800 pipe between the parts. */
function Bar() {
  return <span className="text-[var(--color-neutral-800)]">│</span>
}

/**
 * `GET /api/runs/{id}/requests`: every request of the run, with its
 * answer.
 *
 * `queryFn` is put back explicitly for the reason `./run.ts` gives: the
 * generator declares it optional and `exactOptionalPropertyTypes` will
 * not assign an optional-and-absent property onto `useQuery`'s required
 * one.
 */
function useRequests(runId: string | undefined) {
  const { queryFn, ...options } = getRequestsApiRunsRunIdRequestsGetOptions({
    path: { run_id: runId ?? '' },
  })
  return useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: runId !== undefined,
  })
}

/**
 * The tone an option's label carries: `allow_*` accent, `reject_*`
 * destructive (06 §SPA).
 *
 * The kinds are ACP's and travel verbatim (05 §Policies), so an option
 * that carried none — a `human_input(options=…)` choice, which is a
 * plain label — is drawn plain.
 */
function optionTone(kind: string | null | undefined): string {
  if (typeof kind !== 'string') return 'text-[var(--color-neutral-300)]'
  if (kind.startsWith('allow')) return 'text-[var(--color-accent-300)]'
  if (kind.startsWith('reject')) return 'text-status-fail'
  return 'text-[var(--color-neutral-300)]'
}

/** The choices an `options` request offers, as labels. */
function Options({ options }: { options: readonly RequestOption[] }) {
  return (
    <>
      {options.map((option) => (
        <span
          key={option.option_id}
          data-testid="request-option"
          data-option={option.option_id}
          {...(option.kind == null ? {} : { 'data-kind': option.kind })}
          // A label and not a button: T064 adds the control, and a
          // button that answered nothing would be worse than none.
          className={cn(
            'text-hint rounded-lg bg-[var(--color-neutral-900)] px-[7px] py-[1px]',
            optionTone(option.kind),
          )}
        >
          {option.name}
        </span>
      ))}
    </>
  )
}

/** The bounded summary of the call a permission is about. */
function ToolCall({ tool_call }: { tool_call: unknown }) {
  const summary = toolCallSummary(tool_call)
  if (summary === null) return null

  const heading = [summary.kind, summary.title]
    .filter((part) => part !== undefined)
    .join(' · ')

  return (
    <div
      data-testid="request-tool-call"
      className="bg-zebra mt-[7px] rounded-lg border border-[var(--color-neutral-900)] px-[9px] py-[7px]"
    >
      {heading !== '' && (
        <p
          data-testid="request-tool-heading"
          className="text-hint tracking-[0.1em] text-[var(--color-accent-2-400)]"
        >
          {heading}
        </p>
      )}
      {summary.input !== undefined && (
        <pre
          data-testid="request-tool-input"
          className="text-meta mt-[4px] font-mono whitespace-pre-wrap [overflow-wrap:anywhere] text-[var(--color-neutral-400)]"
        >
          {summary.input}
        </pre>
      )}
      {summary.truncated && (
        <p className="text-hint mt-[4px] text-muted-foreground">
          bounded at {TOOL_CALL_CHARS} characters
        </p>
      )}
    </div>
  )
}

/** The answer, with the author who gave it. */
function Answer({ request }: { request: RequestView }) {
  return (
    <div
      data-testid="request-answer"
      className="mt-[7px] border-t border-[var(--color-neutral-900)] pt-[6px]"
    >
      <p className="text-hint tracking-[0.1em] text-muted-foreground">
        answered by{' '}
        <span
          data-testid="request-author"
          className="text-[var(--color-accent-2-400)]"
        >
          {request.answered_by}
        </span>
      </p>
      <p
        data-testid="request-value"
        className="text-row mt-[3px] whitespace-pre-wrap [overflow-wrap:anywhere] text-[var(--color-neutral-300)]"
      >
        {answerText(request)}
      </p>
    </div>
  )
}

/**
 * Where the answer controls go (T064), and what the card can say in the
 * meantime: the shape of the answer, and the choices on offer.
 */
function Controls({ request }: { request: RequestView }) {
  return (
    <div
      data-testid="request-controls"
      role="group"
      aria-label="answer controls"
      className="mt-[7px] flex flex-wrap items-center gap-[8px] border-t border-dashed border-[var(--color-neutral-800)] pt-[7px]"
    >
      <span className="text-hint tracking-[0.1em] text-status-gate">
        {awaiting(request.mode)}
      </span>
      {request.mode === 'options' && <Options options={request.options ?? []} />}
    </div>
  )
}

/** A question no attempt is left to consume an answer for (08 §Requests). */
function Stale() {
  return (
    <p
      data-testid="request-stale"
      className="text-hint mt-[7px] border-t border-[var(--color-neutral-900)] pt-[6px] text-[var(--color-neutral-500)]"
    >
      unanswered · the attempt that asked has ended
    </p>
  )
}

/** One request: who asked, when, what, and the answer or the slot. */
function Card({ request }: { request: RequestView }) {
  const state = requestState(request)

  return (
    <article
      data-testid="request-card"
      data-request={request.id}
      data-state={state}
      data-kind={request.kind}
      className="rounded-lg border border-[var(--color-neutral-900)] bg-card px-[10px] py-[8px]"
    >
      <div className="mb-[4px] flex flex-wrap items-center gap-x-[8px] gap-y-[4px]">
        <span data-testid="request-from" className="text-row">
          <span className="text-[var(--color-accent-2-400)]">{request.source}</span>
          <span className="text-[var(--color-neutral-500)]"> → </span>
          <span className="text-[var(--color-accent-2-400)]">operator</span>
        </span>
        <Bar />
        <span className="text-hint tracking-[0.1em] text-muted-foreground">
          {request.node}
        </span>
        <Bar />
        <span
          data-testid="request-kind"
          className="text-hint tracking-[0.1em] text-muted-foreground"
        >
          {request.kind}
        </span>
        {state === 'pending' && (
          <span
            aria-hidden="true"
            title="waiting on you"
            className="text-status-gate text-hint"
          >
            {PENDING_GLYPH}
          </span>
        )}
        <div className="flex-1" />
        <span data-testid="request-time" className="text-hint text-muted-foreground">
          {rowTime(request.created)}
        </span>
      </div>

      <p
        data-testid="request-prompt"
        className="text-body whitespace-pre-wrap [overflow-wrap:anywhere] text-[var(--color-neutral-300)]"
      >
        {request.prompt}
      </p>

      {request.kind === 'permission' && <ToolCall tool_call={request.tool_call} />}

      {state === 'answered' ? (
        <Answer request={request} />
      ) : state === 'stale' ? (
        <Stale />
      ) : (
        <Controls request={request} />
      )}
    </article>
  )
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
  const { data, isError, error } = useRequests(runId)

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
              {open > 0 ? `${PENDING_GLYPH} ${open} open` : '○ none open'}
            </span>
          </>
        )}
      </div>

      {runId === undefined ? (
        // The `global` twin of this pane is the inbox — every open
        // request across runs, newest first (06 §SPA) — and it is T064's.
        // Until then the pane says which of the two it is not drawing
        // rather than showing an empty list of the other.
        <div className="p-[12px_14px]">
          <PlaceholderCard
            title="select a run to see the requests it has raised"
            detail="the inbox across every run is not built yet"
          />
        </div>
      ) : isError ? (
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
            <Card key={request.id} request={request} />
          ))}
        </div>
      )}
    </div>
  )
}
