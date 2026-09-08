/**
 * The New Run overlay (`n`, and the palette's first row): the form that
 * queues a run of a workflow (`docs/v1/10-frontend.md` §Overlays, D34,
 * D57).
 *
 * The mock's panel, field for field — `NEW RUN` over `⌘⏎ submit · esc
 * cancel`, a WORKFLOW chip group, TITLE, DESCRIPTION, then POSITION and
 * a read-only ENTRY NODE side by side, then `cancel` and `submit run` —
 * with the one correction 10 makes to it: the 1–10 PRIORITY slider is a
 * top/bottom POSITION choice, because a run's place in the queue is a
 * list position and not a number (D34).
 *
 * **The chips are the server's workflows and the entry node is theirs
 * too.** `GET /api/workflows` carries each workflow's `start` — "the
 * node a new run begins at" — so ENTRY NODE is read from the graph the
 * run will actually walk rather than typed into the mock, and it follows
 * the chip. Nothing is invented for a workflow the server did not send:
 * a registry with nothing in it is a fact about the server, not a
 * failure, and the panel says so and offers nothing to submit.
 *
 * **The form is mounted once the workflows have arrived**, which is what
 * lets react-hook-form take its default workflow from the list instead
 * of correcting itself in an effect a render later. The overlay is a
 * `Dialog`, so its content — and this query with it — exists only while
 * `?overlay=new` is up, and a fresh open is a fresh form.
 *
 * **Two calls, one action** (D57): `submit run` posts the run, and for
 * `top` posts the move to index 0 after it. `newRun.ts` composes them
 * and distinguishes the two refusals, because they are not the same
 * thing to an operator — the first leaves nothing behind and the form
 * stands, the second has already queued the run, so the overlay closes
 * on it and says in a toast that the run is at the bottom. Pressing the
 * button again there would submit a second run.
 *
 * The focus round trip is the palette's, for the palette's reason
 * (`./Palette.tsx`): this dialog opens from a search parameter and has
 * no `Dialog.Trigger`, so Radix would hand focus back to `<body>`. The
 * element that had it is recorded when the dialog takes focus and given
 * it back when the dialog lets go, and the caret goes to TITLE, which is
 * the first thing an operator types.
 *
 * Which of the two of them puts it there depends on whether the form was
 * mounted yet, and it has to, because **Radix skips its own open-focus
 * entirely when something inside the panel already has focus**
 * (`FocusScope` dispatches no `AUTOFOCUS_ON_MOUNT` while the container
 * holds `document.activeElement`). An `autoFocus` on TITLE therefore
 * costs the whole round trip on every open after the first, when the
 * workflows are cached and the form mounts in the same commit as the
 * panel: the handler that records where focus came from never runs, and
 * `esc` drops the operator on `<body>`. Nothing on screen is different,
 * which is why a jsdom suite cannot see it.
 *
 * So the two orders are handled as two, and effects running child-first
 * is what makes them the only two: the dialog's handler focuses TITLE if
 * the form is already there, and the form focuses it on mount if the
 * dialog got there first (`opened`).
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Dialog, ToggleGroup } from 'radix-ui'
import { useCallback, useEffect, useRef } from 'react'
import { Controller, useForm, useWatch } from 'react-hook-form'
import { toast } from 'sonner'

import { listWorkflowsApiWorkflowsGetOptions } from '../api/gen/@tanstack/react-query.gen'
import type { WorkflowOut } from '../api/gen/types.gen'
import { queryKeys } from '../realtime/invalidate'
import { ALL_WORKFLOWS, useUi } from '../store/ui'
import {
  isNewRunFailure,
  newRunSchema,
  POSITIONS,
  submitNewRun,
  type NewRunFailure,
  type NewRunValues,
} from './newRun'

/** The dialog's accessible name, and the mock's header kicker. */
export const NEW_RUN_TITLE = 'new run'

/** What ENTRY NODE reads before a workflow is chosen (02 §Real data only). */
const NO_ENTRY_NODE = '—'

/** The chips of 10 §Components: outlined, accent-tinted when on. */
const CHIP =
  'cursor-pointer rounded-lg border border-border px-[8px] py-[3px] text-[10.5px] ' +
  'text-muted-foreground hover:border-[var(--color-accent-600)] ' +
  'hover:text-[var(--color-accent-200)] data-[state=on]:border-[var(--color-accent-600)] ' +
  'data-[state=on]:bg-accent data-[state=on]:text-[var(--color-accent-200)]'

/** The inputs of 10 §Components: `--color-bg` under a neutral-800 border. */
const FIELD =
  'text-body w-full rounded-lg border border-border bg-background px-[9px] py-[7px] ' +
  'text-foreground outline-none placeholder:text-[var(--color-neutral-600)] ' +
  'focus-visible:border-[var(--color-accent-600)]'

/** The outlined button of 10 §Components, in the two tones a footer needs. */
const BUTTON =
  'text-meta cursor-pointer rounded-lg border px-[12px] py-[5px] ' +
  'disabled:cursor-default disabled:opacity-50'
const NEUTRAL_BUTTON =
  'border-border text-[var(--color-neutral-400)] hover:border-[var(--color-neutral-600)]'
const PRIMARY_BUTTON =
  'border-[var(--color-accent-700)] text-[var(--color-accent-200)] ' +
  'hover:border-[var(--color-accent)] hover:bg-[var(--color-accent-900)]'

/** A field's kicker: the mock's uppercase label over the control. */
function Kicker({ id, children }: { id: string; children: string }) {
  return (
    <div id={id} className="text-kicker mb-[5px] text-[var(--color-neutral-500)]">
      {children}
    </div>
  )
}

/** TITLE's id: the label points at it, and so does the caret. */
const TITLE_ID = 'new-run-title'

export function NewRun({ open, onClose }: { open: boolean; onClose: () => void }) {
  const restoreFocusTo = useRef<HTMLElement | null>(null)
  const panel = useRef<HTMLDivElement | null>(null)
  // Whether the dialog's open-focus has already run. It is what tells a
  // form mounting later that it is the late one, and that the caret is
  // therefore its to take.
  const opened = useRef(false)

  // Stable, because the form runs it from an effect keyed on it: an
  // arrow made per render would re-run that effect on every render of
  // the panel and take the caret back to TITLE mid-sentence.
  const settleCaret = useCallback(() => {
    // The dialog got here first, so the workflows were in flight and the
    // form is the late one: the caret is its to take. Mounted with the
    // panel instead, this runs before the handler below — child effects
    // first — and leaves the caret to it.
    if (opened.current) document.getElementById(TITLE_ID)?.focus()
  }, [])

  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        // `esc`, the backdrop and a click outside all arrive here, so
        // there is one way out and the app writes `?overlay=` away once.
        if (!next) onClose()
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay
          data-testid="new-run-backdrop"
          className="fixed inset-0 z-40 bg-[rgba(10,11,18,.72)]"
        />

        <Dialog.Content
          ref={panel}
          data-testid="new-run"
          // The panel says what it is in two words and describes nothing
          // further; without this Radix warns about the description it
          // cannot find.
          aria-describedby={undefined}
          onOpenAutoFocus={(event) => {
            // The last moment at which the element the operator was on
            // is still the focused one.
            event.preventDefault()
            restoreFocusTo.current =
              document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null
            opened.current = true
            // TITLE if the form is already there; otherwise the panel,
            // so that a modal dialog never leaves focus outside itself,
            // and the form takes the caret when it arrives.
            const title = document.getElementById(TITLE_ID)
            if (title !== null) title.focus()
            else panel.current?.focus()
          }}
          onCloseAutoFocus={(event) => {
            // Radix's own restore goes to a trigger this dialog has not
            // got, which is `<body>` — the operator's place in the app,
            // lost. Ours goes back where focus came from.
            event.preventDefault()
            restoreFocusTo.current?.focus()
            restoreFocusTo.current = null
            opened.current = false
          }}
          className="text-body fixed top-1/2 left-1/2 z-50 max-h-[calc(100dvh-48px)] w-[min(600px,94vw)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-surface)] text-foreground shadow-[var(--shadow-lg)]"
        >
          <div className="flex items-center gap-[10px] border-b border-[var(--color-neutral-900)] px-[14px] py-[10px]">
            <Dialog.Title className="text-kicker text-[var(--color-accent-300)]">
              {NEW_RUN_TITLE}
            </Dialog.Title>
            <div className="flex-1" />
            <span className="text-hint text-muted-foreground">
              ⌘⏎ submit · esc cancel
            </span>
          </div>

          <NewRunBody onClose={onClose} onFormMounted={settleCaret} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/**
 * The workflows, and what the panel is while they are in flight.
 *
 * The three states are three different things and none of them is a
 * form: nothing to choose from yet, a server that could not be asked,
 * and a server that runs no workflows at all.
 */
function NewRunBody({
  onClose,
  onFormMounted,
}: {
  onClose: () => void
  /** The form is on screen: see {@link NewRun}'s note on the caret. */
  onFormMounted: () => void
}) {
  // `queryFn` is put back explicitly for the reason `useRuns` does it
  // (`components/RunList/useRunList.ts`): the generator declares it
  // optional and `exactOptionalPropertyTypes` will not assign an
  // optional-and-absent property onto `useQuery`'s required one.
  const { queryFn, ...options } = listWorkflowsApiWorkflowsGetOptions()
  const { data, isPending, isError } = useQuery({ ...options, queryFn: queryFn! })

  if (isPending || isError || data.length === 0) {
    return (
      <>
        <p
          data-testid="new-run-notice"
          {...(isError ? { role: 'alert' } : {})}
          className="text-meta px-[14px] py-[14px] text-muted-foreground"
        >
          {isPending
            ? 'loading the workflows…'
            : isError
              ? 'the workflows could not be read'
              : 'no workflows are registered'}
        </p>
        <Footer onClose={onClose} />
      </>
    )
  }

  return (
    <NewRunForm workflows={data} onClose={onClose} onMounted={onFormMounted} />
  )
}

/** The form itself, over the workflows the server sent. */
function NewRunForm({
  workflows,
  onClose,
  onMounted,
}: {
  workflows: readonly WorkflowOut[]
  onClose: () => void
  /** Say so once, so the caret can be settled ({@link NewRun}). */
  onMounted: () => void
}) {
  const queryClient = useQueryClient()
  const setRunWorkflow = useUi((state) => state.setRunWorkflow)
  const setRunQuery = useUi((state) => state.setRunQuery)

  const { control, formState, handleSubmit, register } = useForm<NewRunValues>({
    resolver: zodResolver(newRunSchema),
    defaultValues: {
      // The list is sorted by name and non-empty here, so the first chip
      // is a real workflow and the form is submittable the moment it is
      // drawn.
      workflow: workflows[0]?.name ?? '',
      title: '',
      description: '',
      position: 'bottom',
    },
  })

  /**
   * The run is queued; leave the operator looking at it.
   *
   * The list is refetched rather than waited for: `run.submitted` will
   * say the same thing a moment later, but an operator's own submission
   * must appear whether or not this tab's stream is up. The chip and the
   * `/` box are cleared with it, as the mock clears them, because a run
   * submitted under a filter that hides it looks like one that was never
   * queued at all.
   */
  const settle = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
    setRunWorkflow(ALL_WORKFLOWS)
    setRunQuery('')
    onClose()
  }

  // `NewRunFailure` and not the default `Error`: `submitNewRun` rejects
  // with one of those and with nothing else. The guards below are still
  // run, because a bug in this file would reach `onError` as whatever it
  // threw, and a panel that read `.message` off it would show nothing.
  const submission = useMutation<string, NewRunFailure, NewRunValues>({
    mutationFn: submitNewRun,
    onSuccess: settle,
    onError: (error) => {
      // A move that failed after the run was queued cannot be corrected
      // here and must not be retried here: the run exists, and pressing
      // `submit run` again would queue a second one. So the overlay ends
      // as it does on success, and the toast surface carries what the
      // operator did not get (10 §Components).
      if (!isNewRunFailure(error) || error.queued === undefined) return
      toast(error.message)
      settle()
    },
  })

  // `useWatch` and not `watch`: the subscribing form of it is the one
  // that re-renders this component when the chip changes, and the one
  // the React compiler can reason about.
  // Once, on mount: the form is on screen, and the caret can be settled
  // ({@link NewRun}). `onMounted` is stable, so this runs once.
  useEffect(() => {
    onMounted()
  }, [onMounted])

  const chosen = useWatch({ control, name: 'workflow' })
  const entryNode = workflows.find((workflow) => workflow.name === chosen)?.start
  const busy = submission.isPending
  const send = handleSubmit((values) => {
    submission.mutate(values)
  })
  // A refusal of the first call, which is the one the operator can do
  // something about; the second closes the overlay from `onError`.
  const refusal =
    submission.isError && isNewRunFailure(submission.error) ? submission.error : null

  return (
    <form
      data-testid="new-run-form"
      aria-busy={busy}
      onSubmit={(event) => {
        event.preventDefault()
        void send()
      }}
      onKeyDown={(event) => {
        // ⌘⏎ / ^⏎ submits from anywhere in the panel, including the
        // description, where ⏎ alone is a newline (10 §Overlays).
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          event.preventDefault()
          void send()
        }
      }}
    >
      <div className="flex flex-col gap-[12px] p-[14px]">
        <div>
          <Kicker id="new-run-workflow-label">WORKFLOW</Kicker>
          <Controller
            control={control}
            name="workflow"
            render={({ field }) => (
              <ToggleGroup.Root
                type="single"
                value={field.value}
                // A single-mode group reports deselection as `''`. There
                // is no "no workflow" to submit, so the chips are a radio
                // group: pressing the chosen one again leaves it chosen.
                onValueChange={(value) => {
                  if (value !== '') field.onChange(value)
                }}
                onBlur={field.onBlur}
                aria-labelledby="new-run-workflow-label"
                className="flex flex-wrap items-center gap-[5px]"
              >
                {workflows.map((workflow) => (
                  <ToggleGroup.Item
                    key={workflow.name}
                    value={workflow.name}
                    className={CHIP}
                  >
                    {workflow.name}
                  </ToggleGroup.Item>
                ))}
              </ToggleGroup.Root>
            )}
          />
        </div>

        <div>
          <label
            htmlFor={TITLE_ID}
            className="text-kicker mb-[5px] block text-[var(--color-neutral-500)]"
          >
            TITLE
          </label>
          <input
            {...register('title')}
            id={TITLE_ID}
            type="text"
            placeholder="short summary"
            aria-invalid={formState.errors.title !== undefined}
            className={FIELD}
          />
          {formState.errors.title !== undefined && (
            <p
              role="alert"
              data-testid="new-run-title-error"
              className="text-hint mt-[4px] text-status-fail"
            >
              {formState.errors.title.message}
            </p>
          )}
        </div>

        <div>
          <label
            htmlFor="new-run-description"
            className="text-kicker mb-[5px] block text-[var(--color-neutral-500)]"
          >
            DESCRIPTION
          </label>
          <textarea
            {...register('description')}
            id="new-run-description"
            rows={5}
            placeholder="what should the agents do"
            className={`${FIELD} resize-y`}
          />
        </div>

        <div className="grid gap-[12px] [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
          <div>
            <Kicker id="new-run-position-label">POSITION</Kicker>
            <Controller
              control={control}
              name="position"
              render={({ field }) => (
                <ToggleGroup.Root
                  type="single"
                  value={field.value}
                  onValueChange={(value) => {
                    if (value !== '') field.onChange(value)
                  }}
                  onBlur={field.onBlur}
                  aria-labelledby="new-run-position-label"
                  className="flex flex-wrap items-center gap-[5px]"
                >
                  {POSITIONS.map((position) => (
                    <ToggleGroup.Item key={position} value={position} className={CHIP}>
                      {position}
                    </ToggleGroup.Item>
                  ))}
                </ToggleGroup.Root>
              )}
            />
          </div>

          <div>
            <Kicker id="new-run-entry-node-label">ENTRY NODE</Kicker>
            {/* An `output` and not a `div`: it is the one field on the
                panel the operator does not fill in, it is derived from
                the chip beside it, and a screen reader should hear it
                change when the chip does. */}
            <output
              data-testid="new-run-entry-node"
              aria-labelledby="new-run-entry-node-label"
              className="block rounded-lg border border-border bg-background px-[9px] py-[7px] text-[var(--color-neutral-300)]"
            >
              {entryNode ?? NO_ENTRY_NODE}
            </output>
          </div>
        </div>

        {refusal !== null && (
          <p
            role="alert"
            data-testid="new-run-error"
            className="text-meta rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-neutral-900)] px-[9px] py-[5px] text-status-fail"
          >
            {refusal.message}
          </p>
        )}
      </div>

      <Footer onClose={onClose} busy={busy} />
    </form>
  )
}

/**
 * `cancel` and `submit run`, the mock's footer strip.
 *
 * It is drawn under the notices too — a panel with no form still closes,
 * and the button that closes it is where the operator is looking for it
 * — with nothing to submit.
 */
function Footer({
  onClose,
  busy,
}: {
  onClose: () => void
  /** Absent when there is no form: the submit button is not drawn. */
  busy?: boolean
}) {
  return (
    <div className="flex justify-end gap-[8px] border-t border-[var(--color-neutral-900)] px-[14px] py-[12px]">
      <button
        type="button"
        onClick={onClose}
        className={`${BUTTON} ${NEUTRAL_BUTTON}`}
      >
        cancel
      </button>
      {busy !== undefined && (
        <button type="submit" disabled={busy} className={`${BUTTON} ${PRIMARY_BUTTON}`}>
          submit run
        </button>
      )}
    </div>
  )
}
