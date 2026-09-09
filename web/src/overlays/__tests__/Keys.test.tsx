/**
 * `Keys`: "the footer chips, expanded" (`overlays/Keys.tsx`,
 * `docs/v1/10-frontend.md` §Overlays and §Keyboard).
 *
 * The suite **iterates the table** rather than naming rows, so a binding
 * added to `lib/keys.ts` — which `lib/__tests__/keys.test.ts` holds
 * against 10 §Keyboard's own sentence — cannot be forgotten here: the
 * assertion is that the panel draws every one of them, whatever they
 * turn out to be.
 */
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { FOOTER_HINTS, KEY_BINDINGS, KEY_GROUPS, KEY_NOTES } from '../../lib/keys'
import { Keys, KEYS_TITLE } from '../Keys'

/** The overlay over the button that opens it, which `esc` restores to. */
function Harness({ onClose }: { onClose: () => void }) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        open keys
      </button>
      <Keys
        open={open}
        onClose={() => {
          setOpen(false)
          onClose()
        }}
      />
    </>
  )
}

/**
 * Draw the shell and open the overlay.
 *
 * The opener is clicked here rather than in each test because a modal
 * dialog marks the rest of the document `aria-hidden`, so once the panel
 * is up it cannot be found by role at all.
 */
async function open() {
  const user = userEvent.setup()
  const onClose = vi.fn()
  render(<Harness onClose={onClose} />)
  await user.click(screen.getByRole('button', { name: 'open keys' }))
  return { user, onClose }
}

/** One binding's row, by the id the table gave it. */
function row(id: string): HTMLElement {
  const found = screen
    .getByTestId('keys')
    .querySelector<HTMLElement>(`[data-binding="${id}"]`)
  if (found === null) throw new Error(`no row for binding ${id}`)
  return found
}

describe('Keys', () => {
  it('lists every binding of 10 §Keyboard, with its caps and its label', async () => {
    await open()

    for (const binding of KEY_BINDINGS) {
      const line = row(binding.id)
      expect(
        [...line.querySelectorAll('kbd')].map((cap) => cap.textContent),
        `caps for ${binding.id}`,
      ).toEqual([...binding.keys])
      expect(within(line).getByText(binding.label, { exact: false })).toBeInTheDocument()
    }

    expect(screen.getByTestId('keys').querySelectorAll('[data-binding]')).toHaveLength(
      KEY_BINDINGS.length,
    )
  })

  it('is the footer strip expanded, not a second copy of it', async () => {
    await open()

    // Every chip the strip carries is here…
    for (const hint of FOOTER_HINTS) {
      expect(row(hint.id)).toBeInTheDocument()
    }
    // …and the panel carries more, which is what "expanded" means.
    expect(KEY_BINDINGS.length).toBeGreaterThan(FOOTER_HINTS.length)
  })

  it('draws a section per group, in the table’s order', async () => {
    await open()

    const groups = [...screen.getByTestId('keys').querySelectorAll('[data-group]')].map(
      (section) => section.getAttribute('data-group'),
    )

    expect(groups).toEqual([...KEY_GROUPS])
  })

  it('says when a binding does not apply', async () => {
    await open()

    for (const binding of KEY_BINDINGS.filter((one) => one.note !== '')) {
      expect(within(row(binding.id)).getByText(binding.note)).toBeInTheDocument()
    }
  })

  it('carries the rules 10 states about the map', async () => {
    await open()

    const notes = screen.getByTestId('key-notes')
    for (const note of KEY_NOTES) {
      expect(within(notes).getByText(note)).toBeInTheDocument()
    }
  })

  it('names itself, and closes on esc, back where focus came from', async () => {
    const { user, onClose } = await open()

    expect(screen.getByRole('dialog', { name: KEYS_TITLE })).toBeInTheDocument()

    await user.keyboard('{Escape}')

    expect(onClose).toHaveBeenCalledOnce()
    expect(screen.getByRole('button', { name: 'open keys' })).toHaveFocus()
  })

  it('closes on the backdrop, which is the same one way out', async () => {
    const { user, onClose } = await open()

    await user.click(screen.getByTestId('keys-backdrop'))

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('draws nothing while it is closed', () => {
    render(<Harness onClose={vi.fn()} />)

    expect(screen.queryByTestId('keys')).not.toBeInTheDocument()
  })
})
