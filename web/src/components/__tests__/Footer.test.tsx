import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Footer } from '../Footer'

/**
 * The mock's footer row, with 10 §Keyboard's one correction: `D`, drawn
 * as the operator has to type it (`capLabel`, D207).
 */
const HINTS: ReadonlyArray<readonly [string, string]> = [
  ['tab', 'focus'],
  ['t', 'retry task'],
  ['m', 'move task'],
  ['x', 'cancel task'],
  ['l', 'append log'],
  ['n', 'new run'],
  ['r', 'rerun node'],
  ['p', 'pause/resume'],
  ['c', 'cancel run'],
  ['⇧D', 'delete run'],
  ['e', 'edit run'],
  ['w', 'workflows'],
  ['b', 'toggle list'],
  ['?', 'keys'],
]

describe('Footer', () => {
  it('renders a keycap and a label for every hint', () => {
    const { container } = render(<Footer onOpenPalette={() => {}} />)

    expect([...container.querySelectorAll('kbd')].map((k) => k.textContent)).toEqual(
      HINTS.map(([key]) => key),
    )
    for (const [, label] of HINTS) {
      expect(screen.getByText(label)).toBeInTheDocument()
    }
  })

  it('draws delete as the keystroke, so it cannot be read as d', () => {
    // The chip is the app's one always-visible advertisement of the map,
    // and a bare `D` here in an all-lowercase interface is read as `d` —
    // the request panel's deny, which reaches nothing else (D51, D207).
    const { container } = render(<Footer onOpenPalette={() => {}} />)
    const keys = [...container.querySelectorAll('kbd')].map((k) => k.textContent)

    expect(keys).toContain('⇧D')
    expect(keys).not.toContain('D')
    expect(keys).not.toContain('d')
  })

  it('opens the palette', async () => {
    const onOpenPalette = vi.fn()
    render(<Footer onOpenPalette={onOpenPalette} />)

    await userEvent.click(screen.getByRole('button', { name: /palette/ }))
    expect(onOpenPalette).toHaveBeenCalledOnce()
  })
})
