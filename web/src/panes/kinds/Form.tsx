/**
 * The `form` panel kind: the action's own form, in a pane
 * (`docs/v1/09-plugins.md` §Panel kinds, `docs/v1/10-frontend.md`
 * §Plugin renderers).
 *
 * It is the one kind whose `source` is not a URL. A `form` panel names
 * an **action** of the same workflow — registration refuses one that
 * names anything else (09 §Registration and validation, rule 4) — and
 * the form it draws is that action's pydantic model, published in the
 * manifest as JSON Schema. So this pane fetches nothing: everything it
 * needs is already in the manifest the pane host read, and the only
 * request it ever makes is the POST the operator asked for.
 *
 * What draws it is `components/ActionRunner.tsx`, which is the same
 * control the palette's action overlay mounts. This file is the pane's
 * half: find the action the panel named, and say plainly when there is
 * none — a panel pointing at an action this server does not carry is a
 * server this build was not written for, and 09's rule for that is a
 * placeholder card and never a crash.
 */
import { ActionRunner } from '../../components/ActionRunner'
import { actionInvocation, findAction, type ActionSelection } from '../actions'
import { useManifestEntries } from '../manifest'
import { PlaceholderCard } from './cards'

export function FormPane({
  workflow,
  name,
  selection,
}: {
  /** The workflow that declared the panel, and therefore the action. */
  workflow: string
  /** The panel's `source`: the action's name (09 §Panel kinds). */
  name: string
  /** The ids the action may be invoked with (`panes/actions.ts`). */
  selection: ActionSelection
}) {
  const { manifest, isPending } = useManifestEntries()
  const action = findAction(manifest, workflow, name)

  if (action === undefined) {
    return isPending ? (
      <p className="text-row text-muted-foreground" role="status">
        loading {name}…
      </p>
    ) : (
      <PlaceholderCard
        title={`this panel names the action ${name}`}
        detail={`workflow ${workflow} does not declare it`}
      />
    )
  }

  return (
    <ActionRunner
      workflow={workflow}
      action={action}
      invocation={actionInvocation(action, selection)}
      idPrefix={`panel-${workflow}-${name}`}
    />
  )
}
