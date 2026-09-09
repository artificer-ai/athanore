/**
 * What a plugin's actions mean to the browser (`../actions.ts`,
 * `docs/v1/09-plugins.md` §Declarations, §Context and scopes).
 *
 * Every rule here has a counterpart the server enforces
 * (`tests/plugins/test_actions.py`), and the two agree on purpose: an
 * action whose scope this side would not resolve is one the server
 * refuses with `no run in scope`, and the point of resolving it here is
 * that the operator is told what is missing instead of being shown a
 * refusal for it (D158).
 */
import { describe, expect, it } from 'vitest'

import type { ActionOut } from '../../api/gen/types.gen'
import {
  actionHasFields,
  actionId,
  actionInvocation,
  actionResult,
  actionSchema,
  actionTarget,
  actionsOf,
  findAction,
  parseActionId,
  waitingForAction,
} from '../actions'
import { BUILTIN_ENTRY, GAMEDEV_ENTRY, MANIFEST, OTHER_ENTRY, action } from './fixtures'

const RUN = '01JD5XACTIONS0000000000'

const OVERRIDE = GAMEDEV_ENTRY.actions?.[0] as ActionOut
const FLAG = GAMEDEV_ENTRY.actions?.[1] as ActionOut
const RESEED = GAMEDEV_ENTRY.actions?.[2] as ActionOut

describe('actionInvocation', () => {
  it('asks for nothing at all in a workflow or global scope', () => {
    expect(actionInvocation(RESEED, {})).toEqual({})
    expect(actionInvocation(action({ name: 'x', scope: 'workflow' }), {})).toEqual({})
  })

  it('needs the selected run for a run-scoped action', () => {
    expect(actionInvocation(OVERRIDE, {})).toBeNull()
    expect(actionInvocation(OVERRIDE, { runId: RUN })).toEqual({ run_id: RUN })
  })

  it('needs the focused attempt for a task-scoped action', () => {
    expect(actionInvocation(FLAG, { runId: RUN })).toBeNull()
    expect(actionInvocation(FLAG, { runId: RUN, taskId: 12 })).toEqual({
      run_id: RUN,
      task_id: 12,
    })
  })

  it('sends a task on its own when no run is selected with it', () => {
    // The server resolves the run from the attempt (09 §Context and
    // scopes), so a task id is a complete scope by itself.
    expect(actionInvocation(FLAG, { taskId: 12 })).toEqual({ task_id: 12 })
  })

  const NODE = action({ name: 'watch', scope: 'node' })

  it('takes a node-scoped action from the panel that names one', () => {
    expect(actionInvocation(NODE, { runId: RUN, node: 'qa' })).toEqual({
      run_id: RUN,
      node: 'qa',
    })
  })

  it('takes it from the focused attempt when nothing names a node', () => {
    // The node travels with the attempt, which is exactly what the
    // server does with a `task_id` and no `node`.
    expect(actionInvocation(NODE, { runId: RUN, taskId: 12 })).toEqual({
      run_id: RUN,
      task_id: 12,
    })
  })

  it('refuses a node scope with neither', () => {
    expect(actionInvocation(NODE, { runId: RUN })).toBeNull()
    expect(actionInvocation(NODE, { node: 'qa' })).toBeNull()
  })
})

describe('waitingForAction', () => {
  it.each([
    ['run', 'select a run'],
    ['task', 'focus an attempt'],
    ['node', 'focus an attempt'],
    ['global', 'no scope'],
  ])('says what a %s-scoped action is waiting for', (scope, said) => {
    expect(waitingForAction(action({ name: 'x', scope: scope as ActionOut['scope'] })))
      .toContain(said)
  })
})

describe('actionsOf', () => {
  it('lists the builtins and the selected run’s workflow, and no others', () => {
    const listed = actionsOf(MANIFEST, { runId: RUN, workflow: 'gamedev' })

    expect(listed.map((one) => one.workflow)).toEqual(['gamedev', 'gamedev', 'gamedev'])
    expect(listed.map((one) => one.action.name)).toEqual(['override', 'flag', 'reseed'])
  })

  it('excludes another workflow’s actions while its run is not selected', () => {
    const listed = actionsOf(MANIFEST, {
      runId: RUN,
      workflow: OTHER_ENTRY.workflow,
    })

    expect(listed).toEqual([])
  })

  it('lists every workflow’s with nothing selected', () => {
    // No run means no owner, so ownership excludes nothing; what an
    // action needs is then said by its scope, not by this list.
    const listed = actionsOf(MANIFEST, { runId: undefined, workflow: undefined })

    expect(listed.map((one) => one.action.name)).toEqual(['override', 'flag', 'reseed'])
  })

  it('keeps the manifest’s declaration order', () => {
    const listed = actionsOf(
      [{ ...BUILTIN_ENTRY, actions: [action({ name: 'first' })] }, GAMEDEV_ENTRY],
      { runId: RUN, workflow: 'gamedev' },
    )

    expect(listed.map((one) => one.action.name)).toEqual([
      'first',
      'override',
      'flag',
      'reseed',
    ])
  })
})

describe('the id in the URL', () => {
  it('round-trips a workflow and a name', () => {
    expect(parseActionId(actionId('gamedev', 'override'))).toEqual({
      workflow: 'gamedev',
      name: 'override',
    })
  })

  it('refuses anything that is not a pair', () => {
    expect(parseActionId(undefined)).toBeNull()
    expect(parseActionId('override')).toBeNull()
    expect(parseActionId(':override')).toBeNull()
    expect(parseActionId('gamedev:')).toBeNull()
  })
})

describe('findAction', () => {
  it('finds one the manifest carries', () => {
    expect(findAction(MANIFEST, 'gamedev', 'override')).toBe(OVERRIDE)
  })

  it('answers nothing for a workflow or a name it has not got', () => {
    expect(findAction(MANIFEST, 'gamedev', 'ghost')).toBeUndefined()
    expect(findAction(MANIFEST, 'nobody', 'override')).toBeUndefined()
  })
})

describe('what the surfaces read off an action', () => {
  it('hands the schema through as the form', () => {
    expect(actionSchema(OVERRIDE)).toBe(OVERRIDE.schema)
  })

  it('knows a form with fields from one without', () => {
    expect(actionHasFields(OVERRIDE)).toBe(true)
    expect(actionHasFields(RESEED)).toBe(false)
    // A schema of some other form is not known to draw nothing.
    expect(actionHasFields(action({ name: 'x', schema: { $ref: '#/x' } }))).toBe(true)
  })

  it('names what an invocation runs on', () => {
    expect(actionTarget({})).toBe('this server')
    expect(actionTarget({ run_id: RUN })).toBe(`run ${RUN}`)
    expect(actionTarget({ run_id: RUN, task_id: 12, node: 'qa' })).toBe(
      `run ${RUN} · attempt 12 · node qa`,
    )
  })

  it('reports a result without interpreting one', () => {
    // 09 fixes no shape for what a handler returns, so only a plain
    // string is shown; anything else is reported as having run.
    expect(actionResult(OVERRIDE, 'the word is crucible')).toBe(
      'Override secret word · the word is crucible',
    )
    expect(actionResult(OVERRIDE, { word: 'crucible' })).toBe(
      'Override secret word · done',
    )
    expect(actionResult(OVERRIDE, null)).toBe('Override secret word · done')
    expect(actionResult(OVERRIDE, '   ')).toBe('Override secret word · done')
  })
})
