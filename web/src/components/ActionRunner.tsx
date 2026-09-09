/**
 * Running one of a workflow's declared actions: the form, the confirm,
 * and the one POST (`docs/v1/09-plugins.md` §Declarations, §Wire
 * contract; `docs/v1/10-frontend.md` §Plugin renderers).
 *
 * One component in two places — the `form` panel kind
 * (`panes/kinds/Form.tsx`) and the palette's action overlay
 * (`overlays/PluginAction.tsx`) — for the reason `RequestPanel` is one
 * component in three: an action is the same control wherever it is
 * reached from, and two copies would be two chances to disagree about
 * what `confirm` means.
 *
 * Four rules, and each is a decision the docs make:
 *
 * - **the model is the form.** `ActionOut.schema` is the JSON Schema of
 *   the action's pydantic model, and `ActionForm` draws it. There is no
 *   second declaration and no per-action renderer (09 §Declarations).
 * - **`confirm=true` asks first, and cancelling posts nothing.** The
 *   value the operator produced is held while the dialog is up and
 *   dropped if they back out, so the endpoint is never reached for a
 *   call that was withdrawn. It is the browser's guard, not the
 *   server's: `confirm` is advice to the SPA, and an action that must
 *   not run twice enforces that in its handler (09 §Declarations).
 * - **a refusal stays on the form; a success is a toast.** A 422's
 *   `errors` land on the fields that caused them and its sentence above
 *   them, which is the surface that corrects it; anything else the
 *   server said is drawn in the same line, because a form that went
 *   quiet after a failed POST looks like one that succeeded. The toast
 *   is only for the call that landed — and it is what closes the overlay
 *   (D168 (2), D174 (4)).
 * - **it does not ask for what it cannot ask for.** An action whose
 *   scope the selection has not resolved says what it is waiting for
 *   rather than spending a refusal on finding out (D158).
 */
import { useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'

import type { ActionOut, ActionScope } from '../api/gen/types.gen'
import { cn } from '../lib/utils'
import { OverlayDialog, OverlayHeader } from '../overlays/OverlayPanel'
import {
  actionFallback,
  actionResult,
  actionSchema,
  actionTarget,
  useRunAction,
  waitingForAction,
} from '../panes/actions'
import { ActionForm } from './ActionForm'
import { answerFailure } from './answer'

/** The confirm dialog's accessible name, and its header kicker. */
export const CONFIRM_TITLE = 'confirm action'

/** The outlined button of 10 §Components, in the two tones a footer needs. */
const BUTTON =
  'text-meta cursor-pointer rounded-lg border px-[12px] py-[5px] ' +
  'disabled:cursor-default disabled:opacity-50'
const NEUTRAL_BUTTON =
  'border-border text-[var(--color-neutral-400)] hover:border-[var(--color-neutral-600)]'
const ACCENT_BUTTON =
  'border-[var(--color-accent-700)] text-[var(--color-accent-200)] ' +
  'hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-900)]'

export function ActionRunner({
  workflow,
  action,
  invocation,
  idPrefix,
  onDone,
}: {
  /** The workflow whose URL the action is invoked under. */
  workflow: string
  /** The manifest entry: title, scope, `confirm`, and the schema. */
  action: ActionOut
  /**
   * The `scope` object to invoke it with, or `null` when the selection
   * cannot resolve the scope it declared (`panes/actions.ts`).
   */
  invocation: ActionScope | null
  /**
   * What every field id in this form starts with. Required for the
   * reason `ActionForm` requires it: several may be on screen at once.
   */
  idPrefix: string
  /** The call landed. The overlay closes on it; a pane stays put. */
  onDone?: (() => void) | undefined
}) {
  const run = useRunAction()
  // The value waiting behind the confirm dialog. Wrapped in an object so
  // that an action whose form produces `undefined` — one with no fields
  // — is still a pending call rather than no call at all.
  const [pending, setPending] = useState<{ value: unknown } | null>(null)
  const cancelButton = useRef<HTMLButtonElement | null>(null)

  // One object per refusal, and the same object while that refusal
  // stands: `ActionForm` compares by identity to tell a new refusal from
  // a re-render of the one on screen (D168 (3)).
  const failure = useMemo(
    () => (run.isError ? answerFailure(run.error, actionFallback(action)) : null),
    [run.isError, run.error, action],
  )

  if (invocation === null) {
    return (
      <p
        data-testid="action-waiting"
        role="status"
        className="text-row text-muted-foreground"
      >
        {waitingForAction(action)}
      </p>
    )
  }

  const post = (value: unknown) => {
    run.mutate(
      {
        path: { wf: workflow, name: action.name },
        body: { scope: invocation, input: value },
      },
      {
        onSuccess: (data) => {
          toast(actionResult(action, data))
          onDone?.()
        },
      },
    )
  }

  const busy = run.isPending

  return (
    <div
      data-testid="action-runner"
      data-action={action.name}
      data-workflow={workflow}
    >
      <ActionForm
        schema={actionSchema(action)}
        idPrefix={idPrefix}
        submitLabel={action.title}
        busy={busy}
        {...(failure === null
          ? {}
          : { message: failure.message, errors: failure.errors })}
        onSubmit={(value) => {
          if (busy) return
          // `confirm` is asked before the call, not after it: the whole
          // point is that the endpoint is not reached until the operator
          // has said so twice.
          if (action.confirm) setPending({ value })
          else post(value)
        }}
      />

      <OverlayDialog
        open={pending !== null}
        onClose={() => {
          // Backing out posts nothing. There is no call to abort — one
          // was never made — so this is the whole of cancelling.
          setPending(null)
        }}
        testId="action-confirm"
        width="w-[min(440px,94vw)]"
        focusRef={cancelButton}
      >
        <OverlayHeader
          title={CONFIRM_TITLE}
          gloss={`${workflow} · ${action.name}`}
          hint="esc cancel"
        />
        <div className="flex flex-col gap-[10px] px-[14px] py-[14px]">
          <p className="text-row text-[var(--color-neutral-300)]">
            run <span className="text-[var(--color-accent-200)]">{action.title}</span>?
          </p>
          <p data-testid="action-confirm-target" className="text-meta text-muted-foreground">
            it runs on {actionTarget(invocation)}.
          </p>
        </div>
        <div className="flex justify-end gap-[8px] border-t border-[var(--color-neutral-900)] px-[14px] py-[12px]">
          <button
            ref={cancelButton}
            type="button"
            data-testid="action-confirm-cancel"
            onClick={() => {
              setPending(null)
            }}
            className={cn(BUTTON, NEUTRAL_BUTTON)}
          >
            cancel
          </button>
          <button
            type="button"
            data-testid="action-confirm-run"
            onClick={() => {
              if (pending === null) return
              const { value } = pending
              setPending(null)
              post(value)
            }}
            className={cn(BUTTON, ACCENT_BUTTON)}
          >
            {action.title}
          </button>
        </div>
      </OverlayDialog>
    </div>
  )
}
