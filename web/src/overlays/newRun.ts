/**
 * What the New Run overlay is, minus the drawing of it: the shape a
 * submission has to fit, and the two calls that make one
 * (`docs/v1/10-frontend.md` §Overlays, D34, D57).
 *
 * It is a module of its own for the reason `components/answer.ts` is:
 * a file that exports a component and a function is one React Fast
 * Refresh cannot update in place (`.oxlintrc.json`,
 * `react/only-export-components`), and these are the parts worth testing
 * without a DOM.
 *
 * **Submitting at the top of the list is two calls, not one.** There is
 * no "submit at index" endpoint and D57 says there should not be: a run
 * is queued with `POST /api/workflows/{name}/runs` and moved with
 * `POST /api/runs/{id}/position {"index": 0}`, where the index is
 * zero-based, so "top" is those two in order and "bottom" — the position
 * a new run already has — is the first alone. Both have to succeed for
 * the operator to have got what they asked for, which is why the second
 * one's refusal is carried out of here rather than swallowed: the run
 * exists by then, and an overlay that closed silently would leave it
 * queued at the bottom with nobody told.
 */
import { z } from 'zod'

import {
  moveRunApiRunsRunIdPositionPost,
  submitRunApiWorkflowsNameRunsPost,
} from '../api/gen/sdk.gen'

/** Where in the dispatch list the run goes (D34: the mock's slider). */
export const POSITIONS = ['top', 'bottom'] as const

/** The zero-based index "top" means (D57). */
export const TOP_INDEX = 0

/**
 * The form, as zod expresses it.
 *
 * The client blocks exactly what the server does and nothing more (04
 * §Submit a run): the title is stripped of whitespace and may not be
 * empty, which is `Text` in `athanore/api/schemas/bodies.py`, and the
 * description is any string at all including none. The server stays the
 * authority — a workflow that was unregistered between the chips being
 * drawn and the button being pressed is a `409` and is shown as one.
 */
export const newRunSchema = z.object({
  workflow: z.string().min(1, 'choose a workflow'),
  title: z.string().trim().min(1, 'a run needs a title'),
  description: z.string(),
  position: z.enum(POSITIONS),
})

/** One filled-in form: what {@link submitNewRun} takes. */
export type NewRunValues = z.output<typeof newRunSchema>

/** What the overlay says when a POST failed and the body said nothing. */
export const SUBMIT_FALLBACK = 'the run was not queued'

/** ...and when it was queued but the move that followed it failed. */
export const POSITION_FALLBACK = 'the run was queued at the bottom of the list'

/**
 * A refused submission, and whether it left a run behind.
 *
 * `queued` is the whole reason this type exists. A failure of the first
 * call has changed nothing and the operator can correct the form and
 * press the button again; a failure of the *second* has already queued
 * the run, so pressing it again would submit a duplicate. The two are
 * told apart here so that the overlay can say which one happened.
 */
export type NewRunFailure = {
  /** What went wrong, for a person to read. */
  message: string
  /** The run that was queued before the move failed; absent otherwise. */
  queued: string | undefined
}

/** Whether `error` is one of ours rather than something else thrown. */
export function isNewRunFailure(error: unknown): error is NewRunFailure {
  return (
    typeof error === 'object' &&
    error !== null &&
    typeof (error as NewRunFailure).message === 'string' &&
    'queued' in error
  )
}

/**
 * What a refused call said.
 *
 * The generated client throws the parsed error body — `{error, code}`,
 * the API's one error shape (08 §Conventions) — rather than an `Error`,
 * so both are read and neither is assumed, as `panes/kinds/graph.ts`
 * reads a refused node operation and `components/answer.ts` a refused
 * answer.
 */
function refusal(error: unknown, fallback: string): string {
  if (typeof error === 'object' && error !== null) {
    const message = (error as { error?: unknown }).error
    if (typeof message === 'string' && message !== '') return message
    if (error instanceof Error && error.message !== '') return error.message
  }
  if (typeof error === 'string' && error.trim() !== '') return error
  return fallback
}

/**
 * Queue `values` and, for `top`, move the run it made to index 0.
 *
 * Resolves with the new run's id. Rejects with a {@link NewRunFailure}
 * and never with anything else, so the caller has one shape to read
 * whichever of the two calls refused.
 */
export async function submitNewRun(values: NewRunValues): Promise<string> {
  let runId: string

  try {
    const created = await submitRunApiWorkflowsNameRunsPost({
      path: { name: values.workflow },
      // Already trimmed by the schema, which is what the server does to
      // it too; the description is sent as it was typed.
      body: { title: values.title, description: values.description },
      throwOnError: true,
    })
    runId = created.data.run_id
  } catch (error) {
    const failure: NewRunFailure = {
      message: refusal(error, SUBMIT_FALLBACK),
      queued: undefined,
    }
    throw failure
  }

  if (values.position === 'top') {
    try {
      await moveRunApiRunsRunIdPositionPost({
        path: { run_id: runId },
        body: { index: TOP_INDEX },
        throwOnError: true,
      })
    } catch (error) {
      const failure: NewRunFailure = {
        message: refusal(error, POSITION_FALLBACK),
        queued: runId,
      }
      throw failure
    }
  }

  return runId
}
