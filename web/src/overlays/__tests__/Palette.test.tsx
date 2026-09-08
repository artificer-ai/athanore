import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { Palette, PALETTE_TITLE } from '../Palette'
import type { PaletteAction } from '../actions'

function act(over: Partial<PaletteAction> & { id: string }): PaletteAction {
  return {
    name: over.id,
    hint: `what ${over.id} does`,
    key: over.id[0] ?? '?',
    group: null,
    disabled: false,
    run: () => {},
    ...over,
  }
}

const ACTIONS: PaletteAction[] = [
  act({ id: 'new run', hint: 'submit a run against a workflow', key: 'n' }),
  act({ id: 'retry task', hint: 'rerun the focused node', key: 't' }),
  act({ id: 'open workflow library', hint: 'python definitions', key: 'w' }),
  act({ id: 'refresh', hint: 'refetch from the daemon', key: '^r' }),
]

/**
 * The palette over a button that opened it, which is what `esc` has to
 * hand focus back to.
 */
function Harness({ actions = ACTIONS }: { actions?: PaletteAction[] }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        ^p palette
      </button>
      <Palette
        open={open}
        actions={actions}
        onClose={() => {
          setOpen(false)
        }}
      />
    </>
  )
}

async function openPalette(actions?: PaletteAction[]) {
  const user = userEvent.setup()
  render(<Harness {...(actions === undefined ? {} : { actions })} />)
  const opener = screen.getByRole('button', { name: '^p palette' })
  await user.click(opener)
  await screen.findByTestId('palette')
  return { user, opener }
}

function rowNames() {
  return screen.getAllByRole('option').map((row) => row.firstElementChild?.textContent)
}

describe('Palette', () => {
  it('is a dialog with the mock’s prompt and rows', async () => {
    await openPalette()

    const dialog = screen.getByRole('dialog', { name: PALETTE_TITLE })
    expect(within(dialog).getByPlaceholderText('run a command')).toHaveFocus()
    expect(within(dialog).getByText('›')).toBeInTheDocument()
    expect(within(dialog).getByText('esc')).toBeInTheDocument()

    // Every row is `name · hint · key` (10 §Overlays).
    const rows = screen.getAllByRole('option')
    expect(rows).toHaveLength(ACTIONS.length)
    expect([...rows[0]!.children].map((cell) => cell.textContent)).toEqual([
      'new run',
      'submit a run against a workflow',
      'n',
    ])
  })

  it('narrows the list as the operator types', async () => {
    const { user } = await openPalette()

    expect(rowNames()).toHaveLength(ACTIONS.length)

    await user.keyboard('library')

    await waitFor(() => {
      expect(rowNames()).toEqual(['open workflow library'])
    })
  })

  it('matches a command by its hint as well as its name', async () => {
    const { user } = await openPalette()

    await user.keyboard('daemon')

    await waitFor(() => {
      expect(rowNames()).toEqual(['refresh'])
    })
  })

  it('says so when nothing matches', async () => {
    const { user } = await openPalette()

    await user.keyboard('zzzz')

    expect(await screen.findByText('no command matches')).toBeInTheDocument()
    expect(screen.queryAllByRole('option')).toHaveLength(0)
  })

  it('runs the highlighted action on enter', async () => {
    const run = vi.fn()
    const actions = [
      act({ id: 'new run', key: 'n' }),
      act({ id: 'open workflow library', key: 'w', run }),
    ]
    const { user } = await openPalette(actions)

    await user.keyboard('library')
    await waitFor(() => {
      expect(rowNames()).toEqual(['open workflow library'])
    })
    await user.keyboard('{Enter}')

    expect(run).toHaveBeenCalledOnce()
  })

  it('runs the action the arrow keys moved to, not the first one', async () => {
    const first = vi.fn()
    const second = vi.fn()
    const actions = [
      act({ id: 'new run', key: 'n', run: first }),
      act({ id: 'retry task', key: 't', run: second }),
    ]
    const { user } = await openPalette(actions)

    await user.keyboard('{ArrowDown}{Enter}')

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledOnce()
  })

  it('runs an action on click', async () => {
    const run = vi.fn()
    const { user } = await openPalette([act({ id: 'refresh', key: '^r', run })])

    await user.click(screen.getByRole('option', { name: /refresh/ }))

    expect(run).toHaveBeenCalledOnce()
  })

  it('lists a disabled action with its key and refuses to run it', async () => {
    const run = vi.fn()
    const actions = [
      act({ id: 'retry task', key: 't', disabled: true, run }),
      act({ id: 'refresh', key: '^r' }),
    ]
    const { user } = await openPalette(actions)

    const row = screen.getByRole('option', { name: /retry task/ })
    expect(row).toHaveAttribute('aria-disabled', 'true')
    expect(within(row).getByText('t')).toBeInTheDocument()

    await user.click(row)
    expect(run).not.toHaveBeenCalled()

    // Nor does the keyboard reach it: cmdk highlights the next row that
    // is not disabled, so `enter` on a fresh palette runs `refresh`.
    await user.keyboard('{Enter}')
    expect(run).not.toHaveBeenCalled()
  })

  it('closes on esc and gives focus back to what opened it', async () => {
    const { user, opener } = await openPalette()
    expect(opener).not.toHaveFocus()

    await user.keyboard('{Escape}')

    await waitFor(() => {
      expect(screen.queryByTestId('palette')).toBeNull()
    })
    // The part keyboard users notice: without it every palette costs
    // them their place in the app (10 §Accessibility). Radix hands focus
    // back a tick after the panel goes, so this is waited for too.
    await waitFor(() => {
      expect(opener).toHaveFocus()
    })
  })

  it('closes on a click on the backdrop, focus and all', async () => {
    const { user, opener } = await openPalette()

    await user.click(screen.getByTestId('palette-backdrop'))

    await waitFor(() => {
      expect(screen.queryByTestId('palette')).toBeNull()
    })
    await waitFor(() => {
      expect(opener).toHaveFocus()
    })
  })

  it('draws nothing while it is closed', () => {
    render(<Harness />)

    expect(screen.queryByTestId('palette')).toBeNull()
  })

  it('heads a plugin’s actions with its group', async () => {
    // Plugin actions arrive under `plugin: <title>` from T070; the
    // grouping is the palette's and is here now.
    const actions = [
      act({ id: 'new run', key: 'n' }),
      act({ id: 'open review', key: '', group: 'plugin: review' }),
    ]
    await openPalette(actions)

    const group = screen.getByRole('group', { name: 'plugin: review' })
    expect(within(group).getAllByRole('option')).toHaveLength(1)
    expect(rowNames()).toEqual(['new run', 'open review'])
  })
})
