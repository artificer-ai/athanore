import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { Footer } from '../Footer'

/** The mock's footer row, with 10 §Keyboard's one correction: `D`. */
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
  ['D', 'delete run'],
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

  it('shows delete as D, not d (10 §Keyboard)', () => {
    const { container } = render(<Footer onOpenPalette={() => {}} />)
    const keys = [...container.querySelectorAll('kbd')].map((k) => k.textContent)

    expect(keys).toContain('D')
    expect(keys).not.toContain('d')
  })

  it('opens the palette', async () => {
    const onOpenPalette = vi.fn()
    render(<Footer onOpenPalette={onOpenPalette} />)

    await userEvent.click(screen.getByRole('button', { name: /palette/ }))
    expect(onOpenPalette).toHaveBeenCalledOnce()
  })
})
