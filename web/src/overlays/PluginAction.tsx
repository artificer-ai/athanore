/**
 * The palette's plugin actions, run.
 *
 * The palette lists what the app can do and nothing else (`./actions.ts`),
 * so a plugin's action listed there has to be runnable from there — and
 * an action is a form, which needs a surface. This is that surface:
 * `?overlay=action&action=<workflow>:<name>`, one more overlay opened by
 * writing the search, like every other one (10 §Layout).
 *
 * The form, the confirm and the POST are `components/ActionRunner.tsx`,
 * which is also what the `form` panel kind mounts. What this file adds
 * is the dialog around it and the two states the pane never has: an
 * `?action=` that names nothing this server declares, and the close on
 * success — a call that landed has done what the operator opened the
 * overlay for (D174 (4)).
 */
import { ActionRunner } from '../components/ActionRunner'
import {
  findAction,
  actionInvocation,
  parseActionId,
  useManifestEntries,
} from '../panes'
import { OverlayDialog, OverlayHeader } from './OverlayPanel'

/** The dialog's accessible name, and the panel's header kicker. */
export const PLUGIN_ACTION_TITLE = 'run action'

export function PluginAction({
  open,
  action: id,
  runId,
  taskId,
  onClose,
}: {
  open: boolean
  /** `?action=`: `<workflow>:<name>`, or nothing. */
  action: string | undefined
  /** `?run=`: the run an action of `run` scope is invoked on. */
  runId: string | undefined
  /** `?task=`: the attempt a `task`- or `node`-scoped action is invoked on. */
  taskId: number | undefined
  onClose: () => void
}) {
  const named = parseActionId(id)

  return (
    <OverlayDialog
      open={open}
      onClose={onClose}
      testId="plugin-action"
      width="w-[min(560px,94vw)]"
      placement="top"
    >
      <OverlayHeader
        title={PLUGIN_ACTION_TITLE}
        {...(named === null ? {} : { gloss: `${named.workflow} · ${named.name}` })}
        hint="esc cancel"
      />
      <div className="flex-1 overflow-auto px-[14px] py-[14px]">
        <PluginActionBody
          id={id}
          runId={runId}
          taskId={taskId}
          onDone={onClose}
        />
      </div>
    </OverlayDialog>
  )
}

/** The action the search named, or the sentence saying there is none. */
function PluginActionBody({
  id,
  runId,
  taskId,
  onDone,
}: {
  id: string | undefined
  runId: string | undefined
  taskId: number | undefined
  onDone: () => void
}) {
  const { manifest, isPending } = useManifestEntries()
  const named = parseActionId(id)
  const action =
    named === null ? undefined : findAction(manifest, named.workflow, named.name)

  if (named === null) {
    return (
      <p role="status" data-testid="plugin-action-notice" className="text-meta text-muted-foreground">
        pick an action from the palette to run it
      </p>
    )
  }

  if (action === undefined) {
    return (
      <p role="status" data-testid="plugin-action-notice" className="text-meta text-muted-foreground">
        {isPending
          ? `loading ${named.name}…`
          : `this server declares no action ${named.name} on ${named.workflow}`}
      </p>
    )
  }

  return (
    <ActionRunner
      workflow={named.workflow}
      action={action}
      invocation={actionInvocation(action, { runId, taskId })}
      idPrefix={`action-${named.workflow}-${named.name}`}
      onDone={onDone}
    />
  )
}
