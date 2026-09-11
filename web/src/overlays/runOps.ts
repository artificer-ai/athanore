/**
 * The five run-level operator operations that are a button and not a
 * panel: `pause`, `resume`, `cancel`, `reorder` and `delete` (08 §Runs).
 *
 * They have no overlay of their own — `p`, `c` and `D` are keys and
 * palette rows, and `D` opens the one confirm (`./DeleteRun.tsx`) — so
 * the calls live here, in one hook the shell binds once and hands to the
 * palette (10 §Overlays: "every operator action is listed with its key").
 *
 * **`p` is one key over two endpoints.** 04 gives `pause` the
 * precondition `running` or `queued` and `resume` the precondition
 * `paused`, which between them partition every state a run can be
 * paused or resumed in, so the run's own status picks the call and the
 * key never has to be two keys. A terminal run is neither, and the row
 * is disabled rather than posting a `409` to find that out.
 *
 * **`cancel` does not ask and `delete` does.** 10 §Keyboard marks
 * exactly one of them "(with confirm)". The asymmetry is the right one:
 * a cancelled run is still there to read — its attempts, its log, its
 * transcripts — and a deleted one takes "all child rows (tasks, log,
 * events, submissions, stream, requests, answers)" with it. `cancel`
 * reports on the toast what it stopped, which is the `note` only that
 * endpoint fills.
 *
 * **Reorder's palette rows still carry no key, and say so.** They print
 * `—` in the key column rather than a key of their own (D175), because
 * the keyboard's way to this call is a *mode* and not a command: `⏎`
 * picks the selected run up and `↑`/`↓` then move it, which is no row a
 * palette can list (10 §Keyboard, D204 (3)). The New Run overlay's
 * POSITION is the same op with `{index: 0}` (D57), and these three are
 * how a run already in the list moves.
 *
 * Everything here refreshes rather than waiting: `run.paused`,
 * `run.resumed`, `run.cancelled`, `run.reordered` and `run.deleted` all
 * say the same thing a moment later, and an operator's own action must
 * land whether or not this tab's stream is up (D171 (3)).
 */
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  cancelRunApiRunsRunIdCancelPostMutation,
  moveRunApiRunsRunIdPositionPostMutation,
  pauseRunApiRunsRunIdPausePostMutation,
  resumeRunApiRunsRunIdResumePostMutation,
} from '../api/gen/@tanstack/react-query.gen'
import type { RunStatus } from '../api/gen/types.gen'
import { actionError } from '../lib/errors'
import { queryKeys } from '../realtime/invalidate'

/** What each call says when it was refused and the body said nothing. */
export const RUN_OP_FALLBACKS = {
  pause: 'the run was not paused',
  resume: 'the run was not resumed',
  cancel: 'the run was not cancelled',
  reorder: 'the run was not moved',
  delete: 'the run was not deleted',
} as const

/** The statuses `pause` accepts (04 §Operator operations). */
const PAUSABLE: readonly RunStatus[] = ['running', 'queued']

/** Which way `p` goes for a run in `status`, or `null` for neither. */
export function pauseDirection(
  status: RunStatus | undefined,
): 'pause' | 'resume' | null {
  if (status === undefined) return null
  if (status === 'paused') return 'resume'
  return PAUSABLE.includes(status) ? 'pause' : null
}

/** `{direction}` for `POST /api/runs/{id}/position` (08 §Runs). */
export const DIRECTIONS = { up: -1, down: 1 } as const

export type ReorderDirection = keyof typeof DIRECTIONS

/** The run operations, bound to whichever run is selected. */
export type RunOps = {
  /** `p`: pause a running or queued run, resume a paused one. */
  pauseResume: (runId: string, status: RunStatus | undefined) => void
  /** `c`: cancel every attempt of the run. */
  cancel: (runId: string) => void
  /** The palette's `move run up` / `move run down`. */
  reorder: (runId: string, direction: ReorderDirection) => void
}

export function useRunOps(): RunOps {
  const queryClient = useQueryClient()

  /**
   * Refresh the list and the run: both carry the status and the place.
   *
   * `id` names the toast, for the one operation an operator repeats
   * fast: holding `↓` on a focused run posts a swap per keypress, and
   * without an id that is a stack of eight toasts saying eight
   * positions. With one, there is one toast, reporting the last place
   * the server settled on (D204 (4)).
   */
  const settle = (runId: string, note: string, id?: string) => {
    if (id === undefined) toast(note)
    else toast(note, { id })
    void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    void queryClient.invalidateQueries({ queryKey: queryKeys.run(runId) })
  }

  /**
   * Refused: a toast and nothing else.
   *
   * There is no panel to draw the message on — these are keys and
   * palette rows — and every refusal they can meet is a `409` about the
   * run's state, which the operator corrects by looking at the run
   * rather than by retyping anything (10 §Components).
   */
  const refuse = (error: unknown, fallback: string) => {
    toast.error(actionError(error, fallback))
  }

  const pause = useMutation({
    ...pauseRunApiRunsRunIdPausePostMutation(),
    onSuccess: (_data, variables) => {
      settle(variables.path.run_id, 'run paused')
    },
    onError: (error) => {
      refuse(error, RUN_OP_FALLBACKS.pause)
    },
  })

  const resume = useMutation({
    ...resumeRunApiRunsRunIdResumePostMutation(),
    onSuccess: (_data, variables) => {
      settle(variables.path.run_id, 'run resumed')
    },
    onError: (error) => {
      refuse(error, RUN_OP_FALLBACKS.resume)
    },
  })

  const cancel = useMutation({
    ...cancelRunApiRunsRunIdCancelPostMutation(),
    onSuccess: (data, variables) => {
      // `cancel` is the only one of the three that fills `note`, with
      // the number of attempts it stopped (08 §Runs); it is reported
      // rather than replaced by a sentence of our own.
      settle(
        variables.path.run_id,
        data.note == null || data.note === '' ? 'run cancelled' : `run cancelled · ${data.note}`,
      )
    },
    onError: (error) => {
      refuse(error, RUN_OP_FALLBACKS.cancel)
    },
  })

  const reorder = useMutation({
    ...moveRunApiRunsRunIdPositionPostMutation(),
    onSuccess: (data, variables) => {
      // The endpoint answers with the position it settled on, which is
      // the honest thing to report: a run already at the top is a no-op
      // and still a 200 (08 §Runs), and saying "moved" would be a claim
      // the server did not make.
      settle(
        variables.path.run_id,
        `position ${String(data.position)}`,
        `run-position-${variables.path.run_id}`,
      )
    },
    onError: (error) => {
      refuse(error, RUN_OP_FALLBACKS.reorder)
    },
  })

  return {
    pauseResume: (runId, status) => {
      const direction = pauseDirection(status)
      if (direction === null) return
      if (direction === 'pause') pause.mutate({ path: { run_id: runId } })
      else resume.mutate({ path: { run_id: runId } })
    },
    cancel: (runId) => {
      cancel.mutate({ path: { run_id: runId } })
    },
    reorder: (runId, direction) => {
      reorder.mutate({
        path: { run_id: runId },
        body: { direction: DIRECTIONS[direction] },
      })
    },
  }
}
