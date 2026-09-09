/**
 * The palette's `plugin: <workflow>` rows (`../pluginActions.ts`,
 * `docs/v1/09-plugins.md` §Declarations, `docs/v1/10-frontend.md`
 * §Overlays).
 *
 * The palette lists what the app can do and nothing else, so what is
 * asserted here is that every declared action is listed, that a row the
 * selection cannot support is listed and *disabled* rather than hidden,
 * and that running one opens it — the same three rules the app's own
 * catalogue is held to (`./actions.test.ts`).
 */
import { describe, expect, it, vi } from 'vitest'

import type { ActionOut } from '../../api/gen/types.gen'
import { GAMEDEV_ENTRY, MANIFEST } from '../../panes/__tests__/fixtures'
import { actionsOf, type ActionSelection } from '../../panes'
import { KEYLESS, groupActions } from '../actions'
import { actionHint, pluginGroup, pluginPaletteActions } from '../pluginActions'

const RUN = '01JD5XPLUGINACTIONS00000'

/** The rows for the whole manifest, in `at`. */
function rows(at: ActionSelection, open = vi.fn()) {
  return pluginPaletteActions(
    actionsOf(MANIFEST, { runId: at.runId, workflow: 'gamedev' }),
    at,
    open,
  )
}

describe('the rows', () => {
  it('names each action by its title, under its workflow’s heading', () => {
    expect(rows({ runId: RUN }).map((row) => [row.name, row.group])).toEqual([
      ['Override secret word', pluginGroup('gamedev')],
      ['Flag this attempt', pluginGroup('gamedev')],
      ['Reseed the dictionary', pluginGroup('gamedev')],
    ])
  })

  it('advertises no key, because 10 §Keyboard has none to give', () => {
    expect(rows({ runId: RUN }).every((row) => row.key === KEYLESS)).toBe(true)
  })

  it('keys each row by workflow and name, so two workflows may share one', () => {
    expect(rows({ runId: RUN }).map((row) => row.id)).toEqual([
      'plugin:gamedev:override',
      'plugin:gamedev:flag',
      'plugin:gamedev:reseed',
    ])
  })

  it('draws one section per workflow when the rows are grouped', () => {
    const sections = groupActions(rows({ runId: RUN }))

    expect(sections.map((section) => section.group)).toEqual([pluginGroup('gamedev')])
  })

  it.each([
    ['run', 'on the selected run'],
    ['task', 'on the focused attempt'],
    ['node', "on the focused attempt's node"],
    ['workflow', 'on the workflow that declared it'],
    ['global', 'on this server'],
  ])('hints what a %s-scoped action needs', (scope, hint) => {
    const entry = { ...(GAMEDEV_ENTRY.actions?.[0] as ActionOut), scope } as ActionOut
    expect(actionHint(entry)).toBe(hint)
  })
})

describe('what a row does', () => {
  it('opens the action it names', () => {
    const open = vi.fn()

    rows({ runId: RUN }, open)[0]?.run()

    expect(open).toHaveBeenCalledWith('gamedev:override')
  })

  it('disables a row the selection cannot satisfy, and it does nothing', () => {
    const open = vi.fn()
    const listed = rows({ runId: RUN }, open)

    // `run` and `global` are satisfied by a selected run; `task` is not,
    // because no attempt is focused.
    expect(listed.map((row) => row.disabled)).toEqual([false, true, false])
    listed[1]?.run()
    expect(open).not.toHaveBeenCalled()
  })

  it('enables the task-scoped row once an attempt is focused', () => {
    expect(rows({ runId: RUN, taskId: 12 }).map((row) => row.disabled)).toEqual([
      false,
      false,
      false,
    ])
  })

  it('leaves only the global row runnable with nothing selected', () => {
    expect(rows({}).map((row) => row.disabled)).toEqual([true, true, false])
  })
})
