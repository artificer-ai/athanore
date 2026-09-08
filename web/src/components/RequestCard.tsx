/**
 * One request, as both surfaces that list them draw it: the requests
 * pane of a run (`panes/kinds/Requests.tsx`) and the global inbox
 * (`./Inbox.tsx`), which are the same card in two scopes
 * (`docs/v1/10-frontend.md` §Panes item 4, `docs/v1/06-requests.md`
 * §Surfaces).
 *
 * Who asked, when, what, and then either the answer that was given or
 * the controls that give one. The controls are `RequestPanel`, the same
 * component that docks under the agent stream — "answerable in place"
 * (06 §SPA) is one component in three places rather than three controls
 * that have to agree.
 *
 * **A permission carries the tool call.** `tool_call` is the bounded
 * summary `athanore/agents/policies.py` stores when it asks: the title,
 * the ACP kind and the raw input, which together are what an operator
 * decides on. This card bounds it again on the way out, for the reason
 * `TOOL_CALL_CHARS` gives.
 *
 * **The answer's author is drawn, always.** A permission that timed out
 * is answered by `engine` under `permission_timeout_action` (06
 * §Timeouts), and an operator reading back through a run wants to know
 * which answers were theirs and which the clock's.
 */
import type { RequestView } from '../api/gen/types.gen'
import { rowTime } from '../panes/kinds/format'
import {
  TOOL_CALL_CHARS,
  answerText,
  requestState,
  toolCallSummary,
} from '../panes/kinds/requests'
import { RequestPanel } from './RequestPanel'
import { SHORT_ID_LENGTH } from './RunList'

/** The glyph a request waiting on a person carries, as the run list. */
export const PENDING_GLYPH = '⚠'

/** The mock's header separator: a neutral-800 pipe between the parts. */
function Bar() {
  return <span className="text-[var(--color-neutral-800)]">│</span>
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

export function RequestCard({
  request,
  showRun = false,
}: {
  request: RequestView
  /**
   * Whether to name the run this request belongs to.
   *
   * The inbox is the one list that spans runs (06 §SPA), so it is the
   * one that has to say which run each question came out of; inside a
   * run's own pane the answer is the selection and drawing it would be
   * noise.
   */
  showRun?: boolean
}) {
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
        {showRun && (
          <>
            <span
              data-testid="request-run"
              title={request.run_id}
              className="text-hint tracking-[0.1em] text-[var(--color-neutral-400)]"
            >
              run {request.run_id.slice(0, SHORT_ID_LENGTH)}
            </span>
            <Bar />
          </>
        )}
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
        <div
          data-testid="request-controls"
          className="mt-[7px] border-t border-dashed border-[var(--color-neutral-800)] pt-[7px]"
        >
          <RequestPanel request={request} />
        </div>
      )}
    </article>
  )
}
