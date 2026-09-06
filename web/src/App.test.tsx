import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('App', () => {
  it('renders the brand mark and nothing else', () => {
    render(<App />)

    const mark = screen.getByRole('heading', { level: 1 })
    expect(mark).toHaveTextContent('▚ ATHANORE')
    // The dashboard is T057 onward; until then the shell is the mark.
    expect(screen.queryAllByRole('button')).toHaveLength(0)
  })
})
