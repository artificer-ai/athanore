/**
 * `ActionForm`: a form generated from a JSON Schema, in the app's own
 * idiom.
 *
 * RJSF and not a schema walker of our own: `@rjsf/core` with the
 * `@rjsf/shadcn` theme and `validator-ajv8` (02 §Library choices). The
 * theme's components are shadcn's, and shadcn's variables are the
 * Nocturne tokens (10 §Tokens → shadcn), so the form is themed by being
 * mounted rather than by being restyled — the one thing this file adds
 * is the chrome the mock draws around a form: a kicker, a hairline, and
 * the outlined submit/cancel pair of 10 §Components.
 *
 * **The server's own refusal lands on the field that caused it.** A
 * `form` answer is validated where it lands (06 §Service) and refused
 * with `422` and a list of `{loc, msg, type}`; `extraErrorsFrom` turns
 * those `loc` paths into RJSF's `extraErrors`, which is why T030 spends
 * the effort to make `loc` a path rather than a sentence. They are shown
 * beside the fields *and* summarised in one line above the form, because
 * a `loc` naming something the schema does not draw — a validator that
 * knows more than the schema says — must not disappear.
 *
 * **A refusal is cleared by editing, not by resubmitting.** RJSF re-reads
 * `extraErrors` when the prop's reference changes; the first change to
 * the form drops them, so an operator is never left correcting a field
 * under a message about the value they have already replaced.
 *
 * The same component renders `form` requests, elicitations and — from
 * T070 — a plugin action's form. It takes a schema and gives back a
 * value; what that value means belongs to whoever asked.
 */
import { Form } from '@rjsf/shadcn'
import type { ErrorSchema, RJSFSchema } from '@rjsf/utils'
import validator from '@rjsf/validator-ajv8'
import { useMemo, useState } from 'react'

import type { ValidationError } from '../api/gen/types.gen'
import { cn } from '../lib/utils'
import { extraErrorsFrom } from './answer'

/** No server errors: one object, so the memo below has a stable empty. */
const NO_ERRORS: ErrorSchema = {}

/** The outlined button of 10 §Components, in the two tones a form needs. */
const BUTTON =
  'text-meta cursor-pointer rounded-lg border px-[10px] py-[4px] disabled:cursor-default disabled:opacity-50'

export function ActionForm({
  schema,
  idPrefix,
  submitLabel = 'send',
  cancelLabel = 'clear',
  busy = false,
  message,
  errors,
  onSubmit,
  onCancel,
}: {
  /** The JSON Schema the answer must fit (06 §The model). */
  schema: RJSFSchema
  /**
   * What every field id in this form starts with.
   *
   * Required, and not defaulted: several of these are drawn at once —
   * one per card in the requests pane — and RJSF names its inputs from
   * the prefix, so two forms sharing one would give two inputs the same
   * `id` and a label would point at the wrong one.
   */
  idPrefix: string
  /** The submit button's label; `send` unless the caller has a verb. */
  submitLabel?: string
  /** The cancel button's label. */
  cancelLabel?: string
  /** Whether a submission is in flight: both buttons wait for it. */
  busy?: boolean
  /** The whole of a refusal, in one line above the form. */
  message?: string | undefined
  /** A 422's per-field detail, mapped onto the fields by `loc`. */
  errors?: readonly ValidationError[] | undefined
  /** The value the operator produced, once it fits the schema. */
  onSubmit: (value: unknown) => void
  /** Cancel; the form clears itself and the caller hears about it. */
  onCancel?: (() => void) | undefined
}) {
  const [formData, setFormData] = useState<unknown>(undefined)

  // Which mount of the form this is. RJSF treats a `formData` prop of
  // `undefined` as "uncontrolled, keep what you have" rather than as an
  // empty form, so clearing it is a remount: the counter is the `key`,
  // and cancelling bumps it.
  const [generation, setGeneration] = useState(0)

  // Whether the operator has touched the form since the server refused
  // it. A refusal describes the value that was sent, so the first edit
  // is what makes it stale — not the next submission, which would leave
  // the old message under a corrected field for a whole round trip.
  //
  // A new refusal clears the flag **during the render that brings it**,
  // which is React's own way of adjusting state to a changed prop: an
  // effect would render once with the new message and the old flag
  // before correcting itself. The caller keeps one object per refusal
  // (`RequestPanel`), so the comparison is by identity.
  const [edited, setEdited] = useState(false)
  const [seen, setSeen] = useState<{
    message: string | undefined
    errors: readonly ValidationError[] | undefined
  }>({ message, errors })
  if (seen.message !== message || seen.errors !== errors) {
    setSeen({ message, errors })
    setEdited(false)
  }

  const extraErrors = useMemo(
    () => (edited || errors === undefined ? NO_ERRORS : extraErrorsFrom(errors)),
    [edited, errors],
  )

  const notice = edited ? undefined : message

  return (
    <div data-testid="action-form" className="flex flex-col gap-[8px]">
      {notice !== undefined && (
        <p
          data-testid="action-form-message"
          role="alert"
          className="text-meta rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-neutral-900)] px-[9px] py-[5px] text-status-fail"
        >
          {notice}
        </p>
      )}

      <Form
        key={generation}
        schema={schema}
        validator={validator}
        formData={formData}
        extraErrors={extraErrors}
        idPrefix={idPrefix}
        // The errors are drawn beside their fields; the summary above is
        // this file's, so RJSF's own list would be a second copy of it.
        showErrorList={false}
        noHtml5Validate
        disabled={busy}
        onChange={(event) => {
          setFormData(event.formData)
          setEdited(true)
        }}
        onSubmit={(event) => {
          onSubmit(event.formData)
        }}
      >
        <div className="mt-[8px] flex items-center gap-[8px]">
          <button
            type="submit"
            data-testid="action-form-submit"
            disabled={busy}
            className={cn(
              BUTTON,
              'border-[var(--color-accent-700)] text-[var(--color-accent-200)] hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-900)]',
            )}
          >
            {busy ? 'sending…' : submitLabel}
          </button>
          <button
            type="button"
            data-testid="action-form-cancel"
            disabled={busy}
            onClick={() => {
              setFormData(undefined)
              setGeneration((was) => was + 1)
              setEdited(true)
              onCancel?.()
            }}
            className={cn(
              BUTTON,
              'border-border text-[var(--color-neutral-400)] hover:border-[var(--color-neutral-600)] hover:bg-[var(--color-neutral-900)]',
            )}
          >
            {cancelLabel}
          </button>
        </div>
      </Form>
    </div>
  )
}
