/**
 * The palette's `plugin: <workflow>` sections: a workflow's declared
 * actions, as rows (`docs/v1/09-plugins.md` §Declarations,
 * `docs/v1/10-frontend.md` §Overlays).
 *
 * `./actions.ts` is the app's own catalogue and this is the manifest's,
 * kept apart because they are decided by different things: the app's
 * rows are a constant list this build ships, and these arrive from the
 * server and change with what is installed. The palette appends them
 * after the app's, which is where consecutive rows sharing a group are
 * drawn under it (`groupActions`).
 *
 * Three rules, and none of them is new:
 *
 * - **the group is `plugin: <workflow>`.** A plugin has no title of its
 *   own — a `Workflow` has a name — so the workflow's name is what
 *   `plugin: <title>` means, and every action a workflow declares sits
 *   under one heading in declaration order (D181).
 * - **the row's name is the action's `title`**, which 09 defines as
 *   "what the button and the palette entry say". Its hint is the scope
 *   the action needs, because that is what decides whether the row can
 *   be run at all.
 * - **no keys.** 10 §Keyboard is exhaustive and T067 bound exactly it,
 *   so a plugin's action carries `—` in the key column rather than
 *   advertising a key this app has not got (D175).
 *
 * A row the selection cannot support is listed and disabled, like every
 * other row of the palette: the palette is the app's index of itself,
 * and an action that exists and cannot be run right now is exactly what
 * a disabled row says.
 */
import type { ActionOut } from '../api/gen/types.gen'
import { actionId, actionInvocation, type ActionSelection, type PluginAction } from '../panes'
import { KEYLESS, type PaletteAction } from './actions'

/** The heading a workflow's actions are drawn under. */
export function pluginGroup(workflow: string): string {
  return `plugin: ${workflow}`
}

/** The hint column: what the action needs before it can run (09 §Slots). */
export function actionHint(action: ActionOut): string {
  switch (action.scope) {
    case 'run':
      return 'on the selected run'
    case 'task':
      return 'on the focused attempt'
    case 'node':
      return "on the focused attempt's node"
    case 'workflow':
      return 'on the workflow that declared it'
    case 'global':
      return 'on this server'
  }
}

/**
 * The manifest's actions as palette rows, in the manifest's order.
 *
 * `open` writes `?overlay=action&action=<workflow>:<name>`, which both
 * opens the action overlay and closes the palette: one navigation, the
 * same way every other overlay command ends (`./actions.ts`).
 */
export function pluginPaletteActions(
  actions: readonly PluginAction[],
  at: ActionSelection,
  open: (id: string) => void,
): PaletteAction[] {
  return actions.map(({ workflow, action }) => {
    const id = actionId(workflow, action.name)
    const disabled = actionInvocation(action, at) === null

    return {
      id: `plugin:${id}`,
      name: action.title,
      hint: actionHint(action),
      key: KEYLESS,
      group: pluginGroup(workflow),
      disabled,
      run: () => {
        if (disabled) return
        open(id)
      },
    }
  })
}
