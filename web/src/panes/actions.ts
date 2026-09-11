/**
 * A workflow's declared actions: which one a panel or a palette row
 * means, what it has to be invoked with, and the one call that invokes
 * it.
 *
 * An action is not a route. `POST /api/plugins/{wf}/actions/{name}` is
 * one endpoint for the whole server and is therefore a *generated*
 * operation — unlike a plugin route, whose URL only the manifest knows
 * (`./source.ts`) — so this module calls it through the generated
 * mutation like every other typed call in the app.
 *
 * Three rules, and they are the three the server enforces from the other
 * side:
 *
 * - **the ids are the scope's.** An action declares what has to be
 *   resolved before it can run, and {@link actionInvocation} is that
 *   declaration read against the current selection. `null` means the
 *   selection cannot satisfy it, and the surface says what it is waiting
 *   for instead of spending a refusal on finding out — the same rule
 *   `panelParams` follows for a panel's route (D158).
 * - **ownership decides what is listed.** With a run selected, the
 *   actions in view are the builtins' and the run's own workflow's,
 *   because a workflow's declarations apply to its own runs and to no
 *   others (09 §Context and scopes). With no run selected there is no
 *   owner, so every workflow's are listed and their scopes disable what
 *   cannot run.
 * - **the schema is the form.** `ActionOut.schema` is the JSON Schema of
 *   the action's pydantic model — 09's "the model **is** the form" — and
 *   the SPA renders it with `ActionForm` rather than asking a plugin for
 *   a second declaration.
 */
import type { RJSFSchema } from '@rjsf/utils'
import { useMutation } from '@tanstack/react-query'

import { runActionApiPluginsWfActionsNamePostMutation } from '../api/gen/@tanstack/react-query.gen'
import type { ActionOut, ActionScope, PluginManifestEntry } from '../api/gen/types.gen'
import { BUILTIN_WORKFLOW } from './manifest'

/** One action, with the workflow whose URL it is invoked under. */
export type PluginAction = {
  /** The workflow that declared it, `_builtin` for the core's own. */
  workflow: string
  /** The manifest entry itself: title, scope, `confirm`, schema. */
  action: ActionOut
}

/** `<workflow>:<name>`, unique across the manifest and stable in a URL. */
export function actionId(workflow: string, name: string): string {
  return `${workflow}:${name}`
}

/**
 * The `<workflow>:<name>` pair an {@link actionId} names, or `null`.
 *
 * A name may not contain a colon on either side of the wire — a
 * workflow's is a Python identifier and an action's is a URL segment —
 * so the first colon is the separator and the rest is the action.
 */
export function parseActionId(
  id: string | undefined,
): { workflow: string; name: string } | null {
  if (id === undefined) return null
  const at = id.indexOf(':')
  if (at <= 0 || at === id.length - 1) return null
  return { workflow: id.slice(0, at), name: id.slice(at + 1) }
}

/** The action `workflow` declares under `name`, or `undefined`. */
export function findAction(
  manifest: readonly PluginManifestEntry[],
  workflow: string,
  name: string,
): ActionOut | undefined {
  const entry = manifest.find((one) => one.workflow === workflow)
  return (entry?.actions ?? []).find((action) => action.name === name)
}

/**
 * Every action in view, in the manifest's order.
 *
 * Ownership first — the builtins apply to every run, a workflow's apply
 * to its own — and then nothing else: an action whose scope the
 * selection cannot satisfy is *listed and disabled* rather than hidden,
 * because the palette is the app's index of itself (10 §Overlays).
 */
export function actionsOf(
  manifest: readonly PluginManifestEntry[],
  scope: { runId: string | undefined; workflow: string | undefined },
): PluginAction[] {
  const actions: PluginAction[] = []

  for (const entry of manifest) {
    const builtin = entry.workflow === BUILTIN_WORKFLOW
    if (scope.runId !== undefined && !builtin && entry.workflow !== scope.workflow) {
      continue
    }
    for (const action of entry.actions ?? []) {
      actions.push({ workflow: entry.workflow, action })
    }
  }

  return actions
}

/** What the app can offer an action: the selection, and the focused node. */
export type ActionSelection = {
  /** The selected run, from `?run=`. */
  runId?: string | undefined
  /** The focused attempt, from `?task=`. */
  taskId?: number | undefined
  /** A node named outright — a `node`-slot panel's, and no other. */
  node?: string | undefined
}

/**
 * The `scope` object `action` is invoked with, or `null` when the
 * selection cannot resolve it.
 *
 * The server resolves a node from the attempt when none is named, which
 * is why a `node`-scoped action is satisfied by a focused task as well
 * as by a panel that names one.
 */
export function actionInvocation(
  action: ActionOut,
  at: ActionSelection,
): ActionScope | null {
  switch (action.scope) {
    case 'global':
    case 'workflow':
      return {}
    case 'run':
      return at.runId === undefined ? null : { run_id: at.runId }
    case 'task':
      if (at.taskId === undefined) return null
      return {
        ...(at.runId === undefined ? {} : { run_id: at.runId }),
        task_id: at.taskId,
      }
    case 'node':
      if (at.runId === undefined) return null
      if (at.node === undefined && at.taskId === undefined) return null
      return {
        run_id: at.runId,
        ...(at.node === undefined ? {} : { node: at.node }),
        ...(at.taskId === undefined ? {} : { task_id: at.taskId }),
      }
  }
}

/** What an action with an unresolved scope is waiting for. */
export function waitingForAction(action: ActionOut): string {
  switch (action.scope) {
    case 'run':
      return 'select a run to run this action'
    case 'task':
      return 'focus an attempt to run this action'
    case 'node':
      return 'focus an attempt to run this action on its node'
    default:
      return 'this action has no scope to run in'
  }
}

/**
 * What an invocation runs on, for the confirm dialog to name.
 *
 * The ids that are actually being sent, in the order they narrow —
 * never the ones the selection happens to hold — because the sentence is
 * a description of the call about to be made.
 */
export function actionTarget(scope: ActionScope): string {
  const parts: string[] = []
  if (scope.run_id != null) parts.push(`run ${scope.run_id}`)
  if (scope.task_id != null) parts.push(`attempt ${String(scope.task_id)}`)
  if (scope.node != null) parts.push(`node ${scope.node}`)
  return parts.length === 0 ? 'this server' : parts.join(' · ')
}

/** The action's input model, as the schema `ActionForm` draws (09). */
export function actionSchema(action: ActionOut): RJSFSchema {
  return action.schema as RJSFSchema
}

/**
 * Whether the form has anything to fill in.
 *
 * An action that declares no model is published with an object schema
 * carrying no properties (`athanore/plugins/registry.py`), which RJSF
 * draws as a form with nothing but its submit button. That is the right
 * form, and it is also what lets a caller label the button `run` rather
 * than `send` — so the fact is worth reading rather than assuming.
 */
export function actionHasFields(action: ActionOut): boolean {
  const properties = action.schema['properties']
  if (typeof properties !== 'object' || properties === null) {
    // No `properties` at all is a schema of some other form — a `$ref`,
    // an `anyOf` — which RJSF may well draw. Only an *empty* object is
    // known to draw nothing.
    return true
  }
  return Object.keys(properties as Record<string, unknown>).length > 0
}

/** What the surface says when a call was refused and the body said nothing. */
export function actionFallback(action: ActionOut): string {
  return `${action.title} was refused`
}

/**
 * What the toast says when an action landed.
 *
 * 09 fixes no shape for what a handler returns — it is "the handler
 * result (JSON)" — so nothing here interprets it beyond the one case
 * that needs no interpretation: a handler that answered with a plain
 * string said something for a person to read, and it is shown. Anything
 * else is reported as having run, which is the whole of what this side
 * knows (01 §Real data only).
 */
export function actionResult(action: ActionOut, data: unknown): string {
  return typeof data === 'string' && data.trim() !== ''
    ? `${action.title} · ${data.trim()}`
    : `${action.title} · done`
}

/**
 * `POST /api/plugins/{wf}/actions/{name}`, as a mutation.
 *
 * Nothing is invalidated on success, and that is deliberate: an action
 * is a plugin's own code and this side cannot know which resource it
 * touched. What it changed announces itself — an action that moves a run
 * through `ctx.ops` emits `run.*`, and one that changes what a pane
 * draws publishes `plugin.<workflow>.<name>`, which is exactly what a
 * panel's `refresh_on` subscribes to (09 §Wire contract, 10 §Realtime
 * and caching). Guessing here would be a second, wrong invalidation
 * table beside the one the manifest already carries.
 */
export function useRunAction() {
  return useMutation(runActionApiPluginsWfActionsNamePostMutation())
}
