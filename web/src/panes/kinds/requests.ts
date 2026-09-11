/**
 * What the requests pane reads out of a `RequestView`: which of the
 * three states a request is in, the order the cards are drawn in, the
 * bounded tool-call summary a permission carries, and the answer as
 * text.
 *
 * Separate from `./Requests.tsx` for the reason `./format.ts` is
 * separate from the renderers that use it: a module that exports both a
 * component and a function is one React Fast Refresh cannot update in
 * place (`.oxlintrc.json`, `react/only-export-components`). It is also
 * where the pane's two rules that are worth testing without a DOM live —
 * the ordering, and the bound.
 */
import { useQuery } from '@tanstack/react-query'

import { getRequestsApiRunsRunIdRequestsGetOptions } from '../../api/gen/@tanstack/react-query.gen'
import type { RequestOption, RequestView } from '../../api/gen/types.gen'
import { formatValue } from './format'

/**
 * `GET /api/runs/{id}/requests`: every request of the run, with its
 * answer.
 *
 * One query for two readers — the requests pane and the panel docked
 * under the agent stream — so both draw the same list from one cache
 * entry, which is the entry `request.*` invalidates (10 §Realtime and
 * caching).
 *
 * `queryFn` is put back explicitly for the reason `./run.ts` gives: the
 * generator declares it optional and `exactOptionalPropertyTypes` will
 * not assign an optional-and-absent property onto `useQuery`'s required
 * one.
 */
export function useRunRequests(runId: string | undefined) {
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
 * The three states a request card is drawn in.
 *
 * They are the wire's own two booleans plus the author, and they are
 * exhaustive: `pending` is unanswered with an attempt still waiting,
 * `stale` is unanswered with no attempt left to consume an answer, and
 * an answered request is neither (08 §Requests).
 */
export type RequestState = 'pending' | 'answered' | 'stale'

/** Which state `request` is in. */
export function requestState(request: RequestView): RequestState {
  // `answered_by` is the field to test for having an answer at all: the
  // answer itself may legitimately be `null` (08 §Requests).
  if (request.answered_by != null) return 'answered'
  return request.stale ? 'stale' : 'pending'
}

/**
 * The cards, pending first (10 §Panes item 4).
 *
 * Two filters rather than a sort, so the order inside each group is
 * exactly the order the route sent — which is the order the questions
 * were asked, oldest first, and deliberately not a presentation
 * (`athanore/store/repos/requests.py`). Pending on top because those are
 * the ones an operator can act on; the rest below in the order they
 * happened, because that is what a history is.
 */
export function orderRequests(requests: readonly RequestView[]): RequestView[] {
  const pending = requests.filter((request) => requestState(request) === 'pending')
  const rest = requests.filter((request) => requestState(request) !== 'pending')
  return [...pending, ...rest]
}

/** How many of them are still waiting on a person. */
export function pendingCount(requests: readonly RequestView[]): number {
  return requests.filter((request) => requestState(request) === 'pending').length
}

/* -------------------------------------------------------------------- */
/* The tool call a permission is about                                   */
/* -------------------------------------------------------------------- */

/**
 * How much of a tool call this pane will draw, in characters.
 *
 * `athanore/agents/policies.py` already caps what it *stores* at the
 * same figure (`RAW_INPUT_CHARS`), and this is not that bound repeated
 * for its own sake: `tool_call` is an open JSON object on the wire (08
 * §Requests), so what arrives here is whatever the row holds rather than
 * whatever this build's policy module wrote. A card that trusted the
 * producer would be one row away from a pane an operator cannot scroll.
 */
export const TOOL_CALL_CHARS = 500

/** What a permission card shows about the call the agent wants to make. */
export type ToolCallSummary = {
  /** The agent's own title for the call, when it gave one. */
  title?: string
  /** The ACP tool kind (`read`, `edit`, …), when it gave one. */
  kind?: string
  /** The raw input, and anything else the summary carried. */
  input?: string
  /** Whether {@link TOOL_CALL_CHARS} cut the input short. */
  truncated: boolean
}

/** A field of the summary, when it is a string worth drawing. */
function label(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() !== '' ? value : undefined
}

/** Anything that is not already text, as the JSON it is. */
function render(value: unknown): string {
  return typeof value === 'string' ? value : (JSON.stringify(value) ?? String(value))
}

/**
 * The summary of `value`, bounded, or `null` when there is none to draw.
 *
 * `title` and `kind` are the two labelled fields; everything else the
 * object carries is folded into `input` as JSON rather than dropped, so
 * a summary written by a build that recorded more than this one knows
 * about is still shown — bounded, which is the property that matters
 * more than the shape.
 *
 * An empty object is `null` and not an empty card: a permission whose
 * summary says nothing draws no summary block at all.
 */
export function toolCallSummary(value: unknown): ToolCallSummary | null {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return null
  const fields = value as Record<string, unknown>

  const parts: string[] = []
  if (fields['raw_input'] !== undefined) parts.push(render(fields['raw_input']))
  const extra = Object.entries(fields).filter(
    ([key]) => key !== 'title' && key !== 'kind' && key !== 'raw_input',
  )
  if (extra.length > 0) parts.push(render(Object.fromEntries(extra)))

  const whole = parts.join('\n')
  const truncated = whole.length > TOOL_CALL_CHARS
  const input = truncated ? `${whole.slice(0, TOOL_CALL_CHARS)}…` : whole

  const title = label(fields['title'])
  const kind = label(fields['kind'])
  if (title === undefined && kind === undefined && input === '') return null

  return {
    ...(title === undefined ? {} : { title }),
    ...(kind === undefined ? {} : { kind }),
    ...(input === '' ? {} : { input }),
    truncated,
  }
}

/* -------------------------------------------------------------------- */
/* The answer                                                            */
/* -------------------------------------------------------------------- */

/** The option `id` names, among the ones the request offered. */
function chosen(
  options: readonly RequestOption[] | null | undefined,
  id: unknown,
): RequestOption | undefined {
  if (typeof id !== 'string') return undefined
  return (options ?? []).find((option) => option.option_id === id)
}

/**
 * The answer, as the card prints it.
 *
 * An `options` answer is an `option_id`, and an id is not what the
 * operator read when they gave it — so the card shows the option's name
 * with the id beside it, and falls back to the id alone when the request
 * no longer offers it (an answer recorded against a set of options is
 * still the answer that was given).
 *
 * A `form` answer is printed as indented JSON: it is an object by
 * definition (06 §Service), and a card that ran it together on one line
 * would be one an operator has to re-read. Nothing is truncated here —
 * the answer is the thing the card exists to show, and the pane scrolls.
 */
export function answerText(request: RequestView): string {
  const answer = request.answer

  if (request.mode === 'options') {
    const option = chosen(request.options, answer)
    if (option === undefined) return formatValue(answer)
    return option.name === option.option_id
      ? option.option_id
      : `${option.name} · ${option.option_id}`
  }

  if (typeof answer === 'string') return answer
  if (answer === null || answer === undefined) return formatValue(answer)
  return JSON.stringify(answer, null, 2) ?? String(answer)
}

/**
 * What the pane's own request said when it refused.
 *
 * The generated client throws the parsed error body — `{error, code}`,
 * the API's one error shape (08 §Conventions) — rather than an `Error`,
 * so both are read here and neither is assumed. The code travels beside
 * the message because it is the half an operator can look up.
 */
export function requestsError(error: unknown): { message: string; code?: string } {
  if (typeof error === 'object' && error !== null) {
    const fields = error as { error?: unknown; code?: unknown }
    const code = typeof fields.code === 'string' && fields.code !== '' ? fields.code : undefined
    const message = typeof fields.error === 'string' && fields.error !== '' ? fields.error : undefined
    if (message !== undefined) return { message, ...(code === undefined ? {} : { code }) }
    if (error instanceof Error && error.message !== '') {
      return { message: error.message, ...(code === undefined ? {} : { code }) }
    }
  }
  if (typeof error === 'string' && error.trim() !== '') return { message: error }
  return { message: 'the requests could not be loaded' }
}

/** What the controls slot is waiting for, by the shape of the answer. */
export function awaiting(mode: RequestView['mode']): string {
  switch (mode) {
    case 'options':
      return 'awaiting one of'
    case 'text':
      return 'awaiting a text answer'
    case 'form':
      return 'awaiting a form answer'
  }
}

/**
 * The requests of `taskId` a person can still act on, oldest first.
 *
 * What the docked panel draws: "docked under the agent stream when the
 * focused task has open requests" (10 §Panes item 3) is *that attempt's*
 * open questions and no others — a permission raised by the attempt
 * before it belongs to the requests pane's history, not to the turn the
 * operator is watching.
 *
 * The order is the route's, which is the order they were asked. A turn
 * that asked twice before anyone answered gets both, in the order the
 * agent raised them, because that is the order it is waiting in.
 */
export function openRequestsOf(
  requests: readonly RequestView[] | undefined,
  taskId: number | undefined,
): RequestView[] {
  // `Array.isArray` and not a null check: the docked panel is drawn
  // beside a transcript, so a server that answered this route with
  // something else entirely must cost the agent pane nothing.
  if (!Array.isArray(requests) || taskId === undefined) return []
  return requests.filter(
    (request) => request.task_id === taskId && requestState(request) === 'pending',
  )
}
