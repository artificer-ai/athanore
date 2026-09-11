/**
 * `RequestPanel`: the controls that answer one request.
 *
 * **The mode decides the control**, and nothing else does: `options` is
 * one outlined button per option styled by its kind, `text` is an input
 * and a send, `form` is `ActionForm` over the schema the request
 * carries. `kind` and `source` are labels the card draws (06 §The
 * model); a permission and a `human_input` with options are the same
 * control here, because they are the same question.
 *
 * **One POST, and no optimism.** `POST /api/requests/{id}/answer` is the
 * only way an answer is recorded (08 §Requests), and the card is not
 * rewritten until the server has answered: an optimistic panel would
 * show "answered by you" for a request somebody else had already
 * answered. On success the two cache entries that hold this request —
 * the run's list and the inbox — are refetched, so the card the operator
 * just answered redraws from the server's own view of it. The
 * `request.answered` event refreshes the same two entries for every
 * *other* tab (10 §Realtime and caching); this one does not wait for its
 * own event to come back round.
 *
 * **A 409 is a toast, not a silent overwrite.** Two of them (06
 * §Service): the request was answered while the panel was open, or the
 * attempt that asked has ended and the answer would reach nobody.
 * Neither is anything the operator can correct, so the panel says what
 * happened where a transient message belongs and lets the refetched card
 * be the record. Every other refusal is inline — a 422's fields on the
 * form that produced them, and anything else as a line under the
 * controls — because those the operator *can* act on.
 *
 * It is one component in three places: docked under the agent stream,
 * inside a requests-pane card, and inside an inbox card. The panel knows
 * only the request.
 *
 * **`a` and `d` are this panel's keys and nobody else's** (10 §Keyboard,
 * D51). It registers them with the keyboard map against its own root, so
 * they fire for the panel the keystroke came from and for neither of the
 * other two on screen; outside a panel they do nothing at all. They pick
 * by ACP kind — `allow_once` before `allow_always`, `reject_once` before
 * `reject_always` — and are the same POST the buttons make, so a request
 * that offers no such option has no such key.
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import type { RJSFSchema } from '@rjsf/utils'

import { answerRequestApiRequestsRequestIdAnswerPostMutation } from '../api/gen/@tanstack/react-query.gen'
import type { RequestView } from '../api/gen/types.gen'
import { useAnswerKeys } from '../keys'
import { cn } from '../lib/utils'
// The leaf module and not the `panes/kinds` barrel: the barrel exports
// the requests pane, which draws the card that draws this panel, and a
// cycle through it would leave one of the two undefined at module load.
import { awaiting } from '../panes/kinds/requests'
import { queryKeys } from '../realtime/invalidate'
import { ActionForm } from './ActionForm'
import {
  ALLOW_KINDS,
  answerFailure,
  DENY_KINDS,
  isConflict,
  optionClass,
  optionOfKind,
  optionTone,
} from './answer'

/** What the panel says when a POST failed and the body said nothing. */
const FALLBACK = 'the answer was not recorded'

export function RequestPanel({ request }: { request: RequestView }) {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')

  const answer = useMutation({
    ...answerRequestApiRequestsRequestIdAnswerPostMutation(),
    onSuccess: () => {
      setText('')
      refresh()
    },
    onError: (error) => {
      const failure = answerFailure(error, FALLBACK)
      if (!isConflict(failure)) return
      // The request moved under the operator: nothing to correct, and
      // the card is about to be replaced by the server's own view of it.
      toast(failure.message)
      refresh()
    },
  })

  /** Refetch the two entries that hold this request (10 §Realtime). */
  function refresh() {
    void queryClient.invalidateQueries({ queryKey: queryKeys.requests(request.run_id) })
    void queryClient.invalidateQueries({ queryKey: queryKeys.inbox() })
  }

  const busy = answer.isPending
  // One object per refusal, and the same object while that refusal
  // stands: `ActionForm` compares the props it was handed by identity to
  // tell a new refusal from a re-render of the one on screen.
  const failure = useMemo(
    () => (answer.isError ? answerFailure(answer.error, FALLBACK) : null),
    [answer.isError, answer.error],
  )
  // A conflict was a toast and the card is being refetched; repeating it
  // under the controls would leave it on screen after the card had gone.
  const inline = failure !== null && !isConflict(failure) ? failure : null

  const send = (body: { option_id?: string; value?: unknown }) => {
    answer.mutate({ path: { request_id: request.id }, body })
  }

  // `a` and `d`, live only while the keystroke comes from inside this
  // panel (`keys/scope.ts`). A mode with no options, an options request
  // that offers neither kind, and a POST already in flight each leave
  // the key with nothing to do, which is what `null` says.
  const root = useRef<HTMLDivElement | null>(null)
  const byKind = (kinds: readonly string[]): (() => void) | null => {
    if (request.mode !== 'options' || busy) return null
    const option = optionOfKind(request.options, kinds)
    if (option === undefined) return null
    return () => {
      send({ option_id: option.option_id })
    }
  }
  useAnswerKeys(root, { allow: byKind(ALLOW_KINDS), deny: byKind(DENY_KINDS) })

  return (
    <div
      ref={root}
      data-testid="request-panel"
      data-mode={request.mode}
      data-request={request.id}
      role="group"
      aria-label={awaiting(request.mode)}
      aria-busy={busy}
      className="flex flex-col gap-[8px]"
    >
      {request.mode === 'options' && (
        <div className="flex flex-wrap items-center gap-[8px]">
          {(request.options ?? []).map((option) => (
            <button
              key={option.option_id}
              type="button"
              data-testid="request-option"
              data-option={option.option_id}
              data-tone={optionTone(option.kind)}
              {...(option.kind == null ? {} : { 'data-kind': option.kind })}
              disabled={busy}
              onClick={() => {
                send({ option_id: option.option_id })
              }}
              className={cn(
                'text-meta cursor-pointer rounded-lg border px-[10px] py-[4px] disabled:cursor-default disabled:opacity-50',
                optionClass(option.kind),
              )}
            >
              {option.name}
            </button>
          ))}
        </div>
      )}

      {request.mode === 'text' && (
        <form
          className="flex flex-wrap items-center gap-[8px]"
          onSubmit={(event) => {
            event.preventDefault()
            // 06 §Service refuses whitespace alone; the control does not
            // spend a round trip finding that out.
            if (text.trim() === '' || busy) return
            send({ value: text })
          }}
        >
          <input
            type="text"
            data-testid="request-text"
            aria-label="your answer"
            value={text}
            disabled={busy}
            onChange={(event) => {
              setText(event.target.value)
            }}
            placeholder="your answer"
            className="text-row min-w-[200px] flex-1 rounded-lg border border-border bg-background px-[9px] py-[5px] text-[var(--color-neutral-200)] placeholder:text-[var(--color-neutral-600)] disabled:opacity-50"
          />
          <button
            type="submit"
            data-testid="request-send"
            disabled={busy || text.trim() === ''}
            className={cn(
              'text-meta cursor-pointer rounded-lg border px-[10px] py-[4px] disabled:cursor-default disabled:opacity-50',
              'border-[var(--color-accent-700)] text-[var(--color-accent-200)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-900)]',
            )}
          >
            {busy ? 'sending…' : 'send'}
          </button>
        </form>
      )}

      {request.mode === 'form' &&
        (request.schema == null ? (
          // A `form` request is opened with the schema its answer must
          // fit (06 §The model). One without it is a row this build
          // cannot draw a form for, and saying so is better than an
          // empty box that submits nothing.
          <p data-testid="request-no-schema" role="status" className="text-meta text-muted-foreground">
            this form request carries no schema; answer it with{' '}
            <code className="text-[var(--color-accent-200)]">athanore answer</code>
          </p>
        ) : (
          <ActionForm
            schema={request.schema as RJSFSchema}
            idPrefix={`request-${String(request.id)}`}
            busy={busy}
            {...(inline === null ? {} : { message: inline.message, errors: inline.errors })}
            onSubmit={(value) => {
              send({ value })
            }}
          />
        ))}

      {inline !== null && request.mode !== 'form' && (
        <p data-testid="request-error" role="alert" className="text-meta text-status-fail">
          {inline.message}
        </p>
      )}
    </div>
  )
}
