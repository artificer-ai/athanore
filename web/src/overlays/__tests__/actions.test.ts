import { describe, expect, it, vi } from 'vitest'

import {
  PALETTE_COMMANDS,
  buildPaletteActions,
  groupActions,
  type PaletteAction,
  type PaletteContext,
} from '../actions'

function context(over: Partial<PaletteContext> = {}): PaletteContext {
  return {
    runId: 'a4c81f20b91e',
    openOverlay: vi.fn(),
    close: vi.fn(),
    refresh: vi.fn(),
    toggleList: vi.fn(),
    appendLog: vi.fn(),
    ...over,
  }
}

function action(ctx: PaletteContext, id: string) {
  const found = buildPaletteActions(ctx).find((a) => a.id === id)
  if (found === undefined) throw new Error(`no palette command ${id}`)
  return found
}

describe('the palette catalogue', () => {
  it('lists every command with a name, a hint and a key', () => {
    for (const command of PALETTE_COMMANDS) {
      expect(command.name).not.toBe('')
      expect(command.hint).not.toBe('')
      expect(command.key).not.toBe('')
    }
  })

  it('gives every command a unique id and a unique name', () => {
    const ids = PALETTE_COMMANDS.map((c) => c.id)
    const names = PALETTE_COMMANDS.map((c) => c.name)

    expect(new Set(ids).size).toBe(ids.length)
    // cmdk keys an item by its value, which is the name (`Palette.tsx`).
    expect(new Set(names).size).toBe(names.length)
  })

  it('writes delete as 10 §Keyboard does, never as the mock did', () => {
    // The mock bound delete to `d`; 10 §Keyboard moved it to `D` so a
    // `d` meant for "deny" cannot reach the delete confirm. Nothing in
    // the palette may re-advertise the old key.
    expect(PALETTE_COMMANDS.map((c) => c.key)).not.toContain('d')
  })

  it('opens each overlay through `?overlay=`', () => {
    const openOverlay = vi.fn()
    const ctx = context({ openOverlay })

    for (const [id, overlay] of [
      ['new-run', 'new'],
      ['retry-task', 'pick-retry'],
      ['move-task', 'pick-move'],
      ['cancel-task', 'pick-cancel'],
      ['rerun-node', 'pick-rerun'],
      ['edit-run', 'edit'],
      ['workflow-library', 'library'],
      ['keys', 'keys'],
    ] as const) {
      openOverlay.mockClear()
      action(ctx, id).run()
      expect(openOverlay).toHaveBeenCalledExactlyOnceWith(overlay)
    }
  })

  it('does not close the palette when another overlay replaces it', () => {
    const close = vi.fn()
    const ctx = context({ close })

    action(ctx, 'new-run').run()

    // One navigation, not two: `?overlay=new` is what closes the
    // palette, and a close beside it would race its own write.
    expect(close).not.toHaveBeenCalled()
  })

  it('closes the palette and refetches on refresh', () => {
    const ctx = context()

    action(ctx, 'refresh').run()

    expect(ctx.close).toHaveBeenCalledOnce()
    expect(ctx.refresh).toHaveBeenCalledOnce()
  })

  it('lists append log, which the log pane’s composer performs', () => {
    // The composer is on screen today (`panes/kinds/Log.tsx`), so the
    // command belongs to the catalogue today: the palette lists what the
    // app can do, and this is one of the things it can do.
    const command = PALETTE_COMMANDS.find((c) => c.id === 'append-log')

    expect(command?.name).toBe('append log')
    expect(command?.hint).toBe('add a note to the run log')
    expect(command?.key).toBe('l')
  })

  it('closes the palette and shows the composer on append log', () => {
    const ctx = context()

    action(ctx, 'append-log').run()

    expect(ctx.close).toHaveBeenCalledOnce()
    expect(ctx.appendLog).toHaveBeenCalledOnce()
  })

  it('closes the palette and toggles the list on toggle list', () => {
    const ctx = context()

    action(ctx, 'toggle-list').run()

    expect(ctx.close).toHaveBeenCalledOnce()
    expect(ctx.toggleList).toHaveBeenCalledOnce()
  })

  it('disables the run-scoped commands with nothing selected', () => {
    const ctx = context({ runId: undefined })
    const disabled = buildPaletteActions(ctx)
      .filter((a) => a.disabled)
      .map((a) => a.id)

    expect(disabled).toEqual([
      'retry-task',
      'move-task',
      'cancel-task',
      'append-log',
      'rerun-node',
      'edit-run',
    ])
  })

  it('still lists the disabled commands, with their keys', () => {
    const withRun = buildPaletteActions(context()).map((a) => a.id)
    const without = buildPaletteActions(context({ runId: undefined })).map(
      (a) => a.id,
    )

    // The palette doubles as the shortcut list: a row that came and went
    // with the selection would make it a worse one.
    expect(without).toEqual(withRun)
  })

  it('refuses to act on a disabled command however it is reached', () => {
    const ctx = context({ runId: undefined })

    action(ctx, 'retry-task').run()
    action(ctx, 'append-log').run()

    expect(ctx.openOverlay).not.toHaveBeenCalled()
    expect(ctx.appendLog).not.toHaveBeenCalled()
    expect(ctx.close).not.toHaveBeenCalled()
  })

  it('leaves the app commands ungrouped, for plugins to group under', () => {
    // Plugin actions arrive under `plugin: <title>` from T070; the app's
    // own rows are the mock's one flat run.
    expect(buildPaletteActions(context()).every((a) => a.group === null)).toBe(true)
  })
})

/** A row with an id and a heading; nothing else matters to the grouping. */
function row(id: string, group: string | null): PaletteAction {
  return { id, name: id, hint: id, key: id, group, disabled: false, run: () => {} }
}

describe('groupActions', () => {
  it('keeps the catalogue order and opens a section per run of rows', () => {
    const sections = groupActions([
      row('a', null),
      row('b', null),
      row('c', 'plugin: one'),
      row('d', 'plugin: two'),
      row('e', 'plugin: two'),
    ])

    expect(
      sections.map((s) => [s.group, s.actions.map((a) => a.id)]),
    ).toEqual([
      [null, ['a', 'b']],
      ['plugin: one', ['c']],
      ['plugin: two', ['d', 'e']],
    ])
  })

  it('has no sections for no actions', () => {
    expect(groupActions([])).toEqual([])
  })
})
