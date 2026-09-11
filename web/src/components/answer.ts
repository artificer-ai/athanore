/**
 * What the answer controls need that is not a component: how a refusal
 * of `POST /api/requests/{id}/answer` reads, how a 422's `errors[]`
 * becomes something RJSF can put beside a field, and which tone an
 * option's kind carries.
 *
 * Separate from the components for the reason `panes/kinds/format.ts` is
 * separate from the renderers that use it: a module exporting both a
 * component and a function is one React Fast Refresh cannot update in
 * place (`.oxlintrc.json`, `react/only-export-components`). It is also
 * where the three rules worth testing without a DOM live.
 */
import type { ErrorSchema } from '@rjsf/utils'

import type { ErrorCode, RequestOption, ValidationError } from '../api/gen/types.gen'

/**
 * The two refusals that mean the request moved under the operator: it
 * was answered by somebody else, or the attempt that asked has ended.
 *
 * Both are `409` (06 §Service) and both are a toast rather than a form
 * error: there is nothing to correct and nothing to resend, so the panel
 * says what happened and lets the refetched card show the truth.
 */
export const CONFLICT_CODES: readonly ErrorCode[] = ['already_answered', 'stale_request']

/** A refusal, read off the wire's one error shape (08 §Conventions). */
export type AnswerFailure = {
  /** What went wrong, for a person to read. */
  message: string
  /** The stable code, when the body carried one. */
  code: ErrorCode | undefined
  /** The per-field detail of a 422; empty for every other refusal. */
  errors: ValidationError[]
}

/** Whether `entry` is one usable `{loc, msg, type}` of a 422. */
function isValidationError(entry: unknown): entry is ValidationError {
  if (typeof entry !== 'object' || entry === null) return false
  const fields = entry as Partial<ValidationError>
  return Array.isArray(fields.loc) && typeof fields.msg === 'string'
}

/**
 * `error` as this panel reads it.
 *
 * The generated client throws the parsed body — `{error, code, errors?}`
 * — rather than an `Error`, so both are read and neither is assumed,
 * exactly as `panes/kinds/graph.ts` reads a refused node operation. A
 * body that carried nothing usable falls back to `fallback`, because a
 * panel that said nothing after a failed POST would look like one that
 * had answered.
 */
export function answerFailure(error: unknown, fallback: string): AnswerFailure {
  let message: string | undefined
  let code: ErrorCode | undefined
  let errors: ValidationError[] = []

  if (typeof error === 'object' && error !== null) {
    const fields = error as { error?: unknown; code?: unknown; errors?: unknown }
    if (typeof fields.error === 'string' && fields.error !== '') message = fields.error
    if (typeof fields.code === 'string') code = fields.code as ErrorCode
    if (Array.isArray(fields.errors)) errors = fields.errors.filter(isValidationError)
    if (message === undefined && error instanceof Error && error.message !== '') {
      message = error.message
    }
  } else if (typeof error === 'string' && error.trim() !== '') {
    message = error
  }

  return { message: message ?? fallback, code, errors }
}

/** Whether the request moved under the operator (a 409, {@link CONFLICT_CODES}). */
export function isConflict(failure: AnswerFailure): boolean {
  return failure.code !== undefined && CONFLICT_CODES.includes(failure.code)
}

/**
 * A 422's `errors[]` as RJSF's `extraErrors`: one entry beside the field
 * whose value caused it.
 *
 * This is what T030's careful `loc` paths are for. A validator raises
 * `InvalidAnswer` with `loc` as a **path** into the answer —
 * `("outer", "inner", 0)` for the first element of `outer.inner`
 * (`athanore/requests/validators.py`) — and RJSF's `ErrorSchema` is that
 * same path spelled as nesting, with the messages under `__errors`. So
 * the mapping is the path, step for step, and nothing else: a step is
 * used as it arrived, an array index included, because RJSF keys an
 * array's entries by their index too.
 *
 * An error with an empty `loc` is about the answer as a whole and lands
 * on the form's root, which is where RJSF draws an object's own errors.
 * Two errors on one path keep both messages, in the order the server
 * sent them.
 */
export function extraErrorsFrom(errors: readonly ValidationError[]): ErrorSchema {
  const root: ErrorSchema = {}

  for (const error of errors) {
    let at = root
    for (const step of error.loc) {
      const key = String(step)
      const held: unknown = (at as Record<string, unknown>)[key]
      if (typeof held === 'object' && held !== null) {
        at = held as ErrorSchema
      } else {
        const made: ErrorSchema = {}
        ;(at as Record<string, unknown>)[key] = made
        at = made
      }
    }
    at.__errors = [...(at.__errors ?? []), error.msg]
  }

  return root
}

/* -------------------------------------------------------------------- */
/* The options of an `options` request                                   */
/* -------------------------------------------------------------------- */

/** How an option's button is drawn: by what answering it would mean. */
export type OptionTone = 'accent' | 'destructive' | 'neutral'

/**
 * The tone `kind` carries: `allow_*` accent, `reject_*` destructive,
 * anything else neutral (06 §SPA).
 *
 * The kinds are ACP's and travel verbatim (05 §Policies), so an option
 * that carried none — a `human_input(options=…)` choice, which is a
 * plain label — is neutral, and so is a kind this build has never heard
 * of. Neither is a reason to refuse to draw the button.
 */
export function optionTone(kind: string | null | undefined): OptionTone {
  if (typeof kind !== 'string') return 'neutral'
  if (kind.startsWith('allow')) return 'accent'
  if (kind.startsWith('reject')) return 'destructive'
  return 'neutral'
}

/**
 * The outlined button of 10 §Components, in each tone.
 *
 * Outlined and never filled: accent is "a border and a text colour,
 * never a fill" in Nocturne (10 §Tokens → shadcn), and the destructive
 * option follows it so that the two read as one control group.
 */
export const OPTION_CLASSES: Record<OptionTone, string> = {
  accent:
    'border-[var(--color-accent-700)] text-[var(--color-accent-200)] ' +
    'hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-900)]',
  destructive:
    'border-[var(--color-neutral-700)] text-status-fail ' +
    'hover:border-[var(--ath-status-fail)] hover:bg-[var(--color-neutral-900)]',
  neutral:
    'border-border text-[var(--color-neutral-300)] ' +
    'hover:border-[var(--color-neutral-600)] hover:bg-[var(--color-neutral-900)]',
}

/** The classes an option button of this kind carries. */
export function optionClass(kind: string | null | undefined): string {
  return OPTION_CLASSES[optionTone(kind)]
}

/* -------------------------------------------------------------------- */
/* The two keys the request panel adds                                   */
/* -------------------------------------------------------------------- */

/**
 * What `a` picks, in preference order, and what `d` picks.
 *
 * ACP's four permission kinds carry the meaning; the list order a client
 * sends them in is unspecified, so the choice is by kind and never by
 * position. `*_once` before `*_always` is the order 05 §Policies gives
 * `auto_allow` and `auto_deny` and the order `athanore permit` / `deny`
 * uses (11 §Commands): a keystroke answers this one call and does not
 * quietly install a standing rule.
 */
export const ALLOW_KINDS: readonly string[] = ['allow_once', 'allow_always']
export const DENY_KINDS: readonly string[] = ['reject_once', 'reject_always']

/**
 * The first option whose kind is in `kinds`, or `undefined` when the
 * request offers none of them.
 *
 * A `human_input` choice carries no kinds at all (06 §The model), so
 * this is `undefined` for it — and `a` and `d` do nothing there, which
 * is right: they are allow and deny, and that question is neither.
 */
export function optionOfKind(
  options: readonly RequestOption[] | null | undefined,
  kinds: readonly string[],
): RequestOption | undefined {
  for (const kind of kinds) {
    const found = (options ?? []).find((option) => option.kind === kind)
    if (found !== undefined) return found
  }
  return undefined
}
