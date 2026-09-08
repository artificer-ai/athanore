/**
 * The Edit Run overlay (`e`, and the palette's `edit run`): "title and
 * description only" (`docs/v1/10-frontend.md` §Overlays), over `PATCH
 * /api/runs/{id}` (08 §Runs).
 *
 * **Only two fields, and that is the whole design.** The mock's palette
 * row reads "change title, description, priority"; 10 strikes the third,
 * because a run's place in the dispatch list became the New Run
 * overlay's POSITION and `POST /api/runs/{id}/position` (D34, D57) — a
 * list position is reordering, not editing, and putting it here would be
 * a second way to do it that could disagree with the first.
 *
 * **Both fields are sent on every save.** The wire treats an absent
 * field as "leave it alone" — that is why `EditRun.title` and
 * `.description` are optional rather than defaulted (`athanore/api/
 * schemas/bodies.py`) — so a panel that sent only what changed could
 * never blank a description. This one sends what is in the two boxes,
 * and an edit that changed nothing writes nothing and emits nothing,
 * which `Ops.edit` already decides.
 *
 * **A title may not be empty**, the one precondition 04 §Operator
 * operations gives `edit`. The client blocks exactly that and nothing
 * more: the title is trimmed here as the server trims it, and the server
 * stays the authority for everything else — a run deleted between the
 * panel opening and the button being pressed is a `404` and is shown as
 * one.
 *
 * **The form is mounted once the run has arrived**, for the reason the
 * New Run overlay mounts its form once the workflows have (D171 (2)):
 * react-hook-form takes its defaults on mount, and a form drawn over a
 * run still in flight would have to correct itself in an effect a render
 * later — with the operator's own typing to lose if they were quick.
 *
 * The focus round trip is the palette's, for the palette's reason
 * (`./Palette.tsx`), and the caret goes to TITLE by whichever of the
 * panel and the form got there second, never by `autoFocus`, for the
 * reason `./NewRun.tsx` sets out at length.
 */
import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Dialog } from 'radix-ui'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'

import {
  editRunApiRunsRunIdPatchMutation,
  getRunApiRunsRunIdGetOptions,
} from '../api/gen/@tanstack/react-query.gen'
import type { RunDetail } from '../api/gen/types.gen'
import { actionError } from '../lib/errors'
import { queryKeys } from '../realtime/invalidate'

/** The dialog's accessible name, and the mock's header kicker. */
export const EDIT_RUN_TITLE = 'edit run'

/** What the panel says when the `PATCH` was refused and said nothing. */
export const EDIT_RUN_FALLBACK = 'the run was not updated'

/**
 * The form, as zod expresses it.
 *
 * The same two rules the server applies (`Text` in `athanore/api/
 * schemas/bodies.py` and `Ops.edit`'s one precondition): a title
 * stripped of whitespace and not empty, and a description that is any
 * string at all including none.
 */
const editRunSchema = z.object({
  title: z.string().trim().min(1, 'a run needs a title'),
  description: z.string(),
})

type EditRunValues = z.output<typeof editRunSchema>

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

/** TITLE's id: the label points at it, and so does the caret. */
const TITLE_ID = 'edit-run-title'

export function EditRun({
  open,
  runId,
  onClose,
}: {
  open: boolean
  /** `?run=`: the run being edited, or nothing selected. */
  runId: string | undefined
  onClose: () => void
}) {
  const restoreFocusTo = useRef<HTMLElement | null>(null)
  const panel = useRef<HTMLDivElement | null>(null)
  // Whether the dialog's open-focus has already run: it is what tells a
  // form mounting later that the caret is its to take. See `./NewRun.tsx`
  // for why the two orders are handled as two.
  const opened = useRef(false)

  // Stable, because the form runs it from an effect keyed on it.
  const settleCaret = useCallback(() => {
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
          data-testid="edit-run-backdrop"
          className="fixed inset-0 z-40 bg-[rgba(10,11,18,.72)]"
        />

        <Dialog.Content
          ref={panel}
          data-testid="edit-run"
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
              {EDIT_RUN_TITLE}
            </Dialog.Title>
            <div className="flex-1" />
            <span className="text-hint text-muted-foreground">
              ⌘⏎ save · esc cancel
            </span>
          </div>

          <EditRunBody runId={runId} onClose={onClose} onFormMounted={settleCaret} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/**
 * The run, and what the panel is until it has arrived.
 *
 * The three states below are three different things and none of them is
 * a form: no run selected at all, one still in flight, and one this
 * server could not answer for.
 */
function EditRunBody({
  runId,
  onClose,
  onFormMounted,
}: {
  runId: string | undefined
  onClose: () => void
  /** The form is on screen: see {@link EditRun}'s note on the caret. */
  onFormMounted: () => void
}) {
  // `queryFn` is put back explicitly for the reason `useRuns` does it
  // (`components/RunList/useRunList.ts`): the generator declares it
  // optional and `exactOptionalPropertyTypes` will not assign an
  // optional-and-absent property onto `useQuery`'s required one.
  const { queryFn, ...options } = getRunApiRunsRunIdGetOptions({
    path: { run_id: runId ?? '' },
  })
  const { data, isPending, isError, error } = useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: runId !== undefined,
  })

  if (runId === undefined || isPending || isError) {
    return (
      <>
        <p
          data-testid="edit-run-notice"
          {...(isError ? { role: 'alert' } : { role: 'status' })}
          className="text-meta px-[14px] py-[14px] text-muted-foreground"
        >
          {runId === undefined
            ? 'select a run to edit it'
            : isError
              ? actionError(error, 'this run could not be read')
              : 'loading the run…'}
        </p>
        <Footer onClose={onClose} />
      </>
    )
  }

  return <EditRunForm run={data} onClose={onClose} onMounted={onFormMounted} />
}

/** The two fields, over the run the server sent. */
function EditRunForm({
  run,
  onClose,
  onMounted,
}: {
  run: RunDetail
  onClose: () => void
  /** Say so once, so the caret can be settled ({@link EditRun}). */
  onMounted: () => void
}) {
  const queryClient = useQueryClient()
  // Whether a save is out. A ref and not `isPending`, for the reason
  // D171 (1) gives: ⌘⏎ never consults the button, and the pending state
  // arrives a render later.
  const sending = useRef(false)
  const [refusal, setRefusal] = useState<string | null>(null)

  const { formState, handleSubmit, register } = useForm<EditRunValues>({
    resolver: zodResolver(editRunSchema),
    defaultValues: { title: run.title, description: run.description ?? '' },
  })

  const save = useMutation({
    ...editRunApiRunsRunIdPatchMutation(),
    onSuccess: () => {
      // The run list carries the title and the run detail carries both,
      // and they are refreshed rather than waited for: `run.updated`
      // will say the same thing a moment later, and an operator's own
      // edit must land whether or not this tab's stream is up.
      void queryClient.invalidateQueries({ queryKey: queryKeys.runs() })
      void queryClient.invalidateQueries({ queryKey: queryKeys.run(run.id) })
      onClose()
    },
    onError: (error) => {
      // Correctable here — a title some later rule rejects, a run
      // deleted while the panel was open — so the panel stays up with
      // the message under the fields rather than closing on it.
      setRefusal(actionError(error, EDIT_RUN_FALLBACK))
    },
    onSettled: () => {
      sending.current = false
    },
  })

  // Once, on mount: the form is on screen, and the caret can be settled
  // ({@link EditRun}). `onMounted` is stable, so this runs once.
  useEffect(() => {
    onMounted()
  }, [onMounted])

  /**
   * Save, once. The button and ⌘⏎ both come through here, and the latch
   * is taken before validation rather than after it, because validation
   * is async: two presses in one tick would otherwise both find nothing
   * in flight.
   */
  const send = () => {
    if (sending.current) return
    sending.current = true
    setRefusal(null)
    let sent = false
    void handleSubmit((values) => {
      sent = true
      save.mutate({
        path: { run_id: run.id },
        // Both fields, every time: an absent one means "leave it alone"
        // on the wire, so a description cleared here has to travel as
        // the empty string it now is.
        body: { title: values.title, description: values.description },
      })
    })().then(() => {
      if (!sent) sending.current = false
    })
  }

  const busy = save.isPending

  return (
    <form
      data-testid="edit-run-form"
      aria-busy={busy}
      onSubmit={(event) => {
        event.preventDefault()
        send()
      }}
      onKeyDown={(event) => {
        // ⌘⏎ / ^⏎ saves from anywhere in the panel, including the
        // description, where ⏎ alone is a newline (10 §Overlays).
        if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
          event.preventDefault()
          send()
        }
      }}
    >
      <div className="flex flex-col gap-[12px] p-[14px]">
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
              data-testid="edit-run-title-error"
              className="text-hint mt-[4px] text-status-fail"
            >
              {formState.errors.title.message}
            </p>
          )}
        </div>

        <div>
          <label
            htmlFor="edit-run-description"
            className="text-kicker mb-[5px] block text-[var(--color-neutral-500)]"
          >
            DESCRIPTION
          </label>
          <textarea
            {...register('description')}
            id="edit-run-description"
            rows={5}
            placeholder="what should the agents do"
            className={`${FIELD} resize-y`}
          />
        </div>

        {refusal !== null && (
          <p
            role="alert"
            data-testid="edit-run-error"
            className="text-meta rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-neutral-900)] px-[9px] py-[5px] text-status-fail"
          >
            {refusal}
          </p>
        )}
      </div>

      <Footer onClose={onClose} busy={busy} />
    </form>
  )
}

/**
 * `cancel` and `save`, the New Run overlay's footer strip.
 *
 * It is drawn under the notices too — a panel with no form still closes,
 * and the button that closes it is where the operator is looking for it
 * — with nothing to save.
 */
function Footer({
  onClose,
  busy,
}: {
  onClose: () => void
  /** Absent when there is no form: the save button is not drawn. */
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
          save
        </button>
      )}
    </div>
  )
}
