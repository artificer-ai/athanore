import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { DEFAULT_LIST_WIDTH, usePrefs } from './store/prefs'
import { useUi } from './store/ui'

function shell(search = {}) {
  return render(<App search={search} onOpenPalette={() => {}} />)
}

describe('App', () => {
  beforeEach(() => {
    usePrefs.setState({ listWidth: DEFAULT_LIST_WIDTH })
    useUi.setState({ focus: 'list' })
  })

  it('renders the four regions of 10 §Layout', () => {
    shell()

    expect(screen.getByRole('banner')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'runs' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'detail' })).toBeInTheDocument()
    expect(screen.getByRole('contentinfo')).toBeInTheDocument()
  })

  it('lays the run list out at the width prefs holds', () => {
    usePrefs.setState({ listWidth: 400 })
    shell()

    // The splitter that lets the operator drag this width is T058a's;
    // the shell reads it either way.
    const list = screen.getByRole('region', { name: 'runs' }).parentElement
    expect(list).toHaveStyle({ width: '400px' })
  })

  it('passes the selected run through to the pane bar', () => {
    shell({ run: 'a4c81f20b91e' })

    expect(screen.getByTestId('selected-run')).toHaveTextContent('a4c81f20b91e')
  })

  it('asks for the palette from the footer', async () => {
    const onOpenPalette = vi.fn()
    render(<App search={{}} onOpenPalette={onOpenPalette} />)

    await userEvent.click(screen.getByRole('button', { name: /palette/ }))
    expect(onOpenPalette).toHaveBeenCalledOnce()
  })
})
