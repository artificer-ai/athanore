/**
 * The delete confirm (`D`, and the palette's `delete run`): the one
 * overlay the keyboard map marks "(with confirm)".
 *
 * `delete(run)` is the only operator operation of 04 that destroys
 * anything: it cancels the run and then deletes it "and **all** child
 * rows (tasks, log, events, submissions, stream, requests, answers)".
 * Nothing else in the app is unrecoverable, so nothing else asks — and
 * the panel says what goes rather than asking "are you sure", because
 * the operator's decision turns on what is about to be lost.
 *
 * **The key is `D`, not `d`.** 10 §Keyboard moved it, so that a `d`
 * meant for "deny" one focus ring away cannot reach this dialog. The
 * confirm is the second guard, not the first.
 *
 * **`delete` closes the run, not just the overlay.** A run that no
 * longer exists cannot be the selection, so the app is told to clear
 * `?run=` on the way out; the run list would otherwise sit on a row the
 * next `GET /api/runs` will not carry, and the detail pane would ask for
 * a run that answers 404.
 *
 * The dangerous button is the destructive one and the safe one is
 * focused: `⏎` on an overlay that appeared under the operator's fingers
 * must cancel, not delete.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useRef, useState, type RefObject } from 'react'

import {
  deleteRunApiRunsRunIdDeleteMutation,
  getRunApiRunsRunIdGetOptions,
} from '../api/gen/@tanstack/react-query.gen'
import { actionError } from '../lib/errors'
import { queryKeys } from '../realtime/invalidate'
import { RUN_OP_FALLBACKS } from './runOps'
import { OverlayDialog, OverlayHeader } from './OverlayPanel'

/** The dialog's accessible name, and the panel's header kicker. */
export const DELETE_RUN_TITLE = 'delete run'

/** What goes with the run (04 §Operator operations, `delete`). */
export const DELETE_RUN_LOSES =
  'its attempts, work log, events, submissions, agent transcripts, requests and answers'

/** The outlined button of 10 §Components, in the two tones a footer needs. */
const BUTTON =
  'text-meta cursor-pointer rounded-lg border px-[12px] py-[5px] ' +
  'disabled:cursor-default disabled:opacity-50'
const NEUTRAL_BUTTON =
  'border-border text-[var(--color-neutral-400)] hover:border-[var(--color-neutral-600)]'
const DESTRUCTIVE_BUTTON =
  'border-status-fail text-status-fail hover:bg-[var(--color-neutral-900)]'

export function DeleteRun({
  open,
  runId,
  onClose,
  onDeleted,
}: {
  open: boolean
  /** `?run=`: the run being deleted, or nothing selected. */
  runId: string | undefined
  onClose: () => void
  /** The run is gone: clear the selection as well as the overlay. */
  onDeleted?: (() => void) | undefined
}) {
  const cancelButton = useRef<HTMLButtonElement | null>(null)

  return (
    <OverlayDialog
      open={open}
      onClose={onClose}
      testId="delete-run"
      width="w-[min(480px,94vw)]"
      focusRef={cancelButton}
    >
      <OverlayHeader title={DELETE_RUN_TITLE} hint="esc cancel" />
      <DeleteRunBody
        runId={runId}
        cancelRef={cancelButton}
        onClose={onClose}
        onDeleted={onDeleted}
      />
    </OverlayDialog>
  )
}

/** What is about to go, and the two buttons. */
function DeleteRunBody({
  runId,
  cancelRef,
  onClose,
  onDeleted,
}: {
  runId: string | undefined
  cancelRef: RefObject<HTMLButtonElement | null>
  onClose: () => void
  onDeleted?: (() => void) | undefined
}) {
  const queryClient = useQueryClient()
  const [refusal, setRefusal] = useState<string | null>(null)
  // Whether the call is out. A ref and not `isPending`, for the reason
  // D171 (1) gives: the pending state arrives a render later, and this
  // is the one action in the app that cannot be un-done.
  const sending = useRef(false)

  // `queryFn` is put back explicitly for the reason `useRuns` does it
  // (`components/RunList/useRunList.ts`): the generator declares it
  // optional and `exactOptionalPropertyTypes` will not assign an
  // optional-and-absent property onto `useQuery`'s required one.
  const { queryFn, ...options } = getRunApiRunsRunIdGetOptions({
    path: { run_id: runId ?? '' },
  })
  const run = useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: runId !== undefined,
  })

  const remove = useMutation({
    ...deleteRunApiRunsRunIdDeleteMutation(),
    onSuccess: (_data, variables) => {
      // The run's own cache entries are dropped rather than refetched:
      // every one of them is now a 404, and a refetch would raise the
      // error screen over an operator who got exactly what they asked
      // for.
      queryClient.removeQueries({ queryKey: queryKeys.run(variables.path.run_id) })
      queryClient.removeQueries({ queryKey: queryKeys.graph(variables.path.run_id) })
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
      onDeleted?.()
      onClose()
    },
    onError: (error) => {
      sending.current = false
      setRefusal(actionError(error, RUN_OP_FALLBACKS.delete))
    },
  })

  const title = run.data?.title

  return (
    <>
      <div className="flex flex-col gap-[10px] px-[14px] py-[14px]">
        {runId === undefined ? (
          <p role="status" data-testid="delete-run-notice" className="text-meta text-muted-foreground">
            select a run to delete it
          </p>
        ) : (
          <>
            <p className="text-row text-[var(--color-neutral-300)]">
              delete run{' '}
              <span className="text-[var(--color-accent-200)]">{runId}</span>
              {title === undefined ? '' : ` — ${title}`}?
            </p>
            <p className="text-meta text-muted-foreground">
              this also deletes {DELETE_RUN_LOSES}. it cannot be undone.
            </p>
          </>
        )}

        {refusal !== null && (
          <p
            role="alert"
            data-testid="delete-run-error"
            className="text-meta rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-neutral-900)] px-[9px] py-[5px] text-status-fail"
          >
            {refusal}
          </p>
        )}
      </div>

      <div className="flex justify-end gap-[8px] border-t border-[var(--color-neutral-900)] px-[14px] py-[12px]">
        <button
          ref={cancelRef}
          type="button"
          onClick={onClose}
          className={`${BUTTON} ${NEUTRAL_BUTTON}`}
        >
          cancel
        </button>
        <button
          type="button"
          disabled={runId === undefined || remove.isPending}
          onClick={() => {
            if (runId === undefined || sending.current) return
            sending.current = true
            setRefusal(null)
            remove.mutate({ path: { run_id: runId } })
          }}
          className={`${BUTTON} ${DESTRUCTIVE_BUTTON}`}
        >
          delete run
        </button>
      </div>
    </>
  )
}
