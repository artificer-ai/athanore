import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useUi } from '../../store/ui'
import { PluginAssetsBanner, STALE_ASSETS_NOTICE } from '../PluginAssetsBanner'

const V2 = '/plugins/tempo/static/tempo.js?v=bbbbbbbbbbbb'

describe('PluginAssetsBanner', () => {
  afterEach(() => {
    useUi.setState({ staleAssets: {} })
  })

  it('says nothing while every module this page ran is the one listed', () => {
    render(<PluginAssetsBanner />)

    expect(screen.queryByTestId('plugin-assets-banner')).toBeNull()
  })

  it('says which plugins’ code changed, and that a reload is the way to it', () => {
    useUi.getState().markStaleAssets('tempo', [V2])
    useUi.getState().markStaleAssets('gamedev', ['/plugins/gamedev/static/p.js?v=2'])

    render(<PluginAssetsBanner />)

    const banner = screen.getByTestId('plugin-assets-banner')
    expect(banner).toHaveAttribute('role', 'status')
    expect(banner).toHaveTextContent(STALE_ASSETS_NOTICE)
    expect(banner).toHaveTextContent('plugin code changed — reload the page')
    // Sorted, so the strip reads the same however the reloads arrived.
    expect(
      screen.getAllByTestId('plugin-assets-workflow').map((code) => code.textContent),
    ).toEqual(['gamedev', 'tempo'])
  })

  it('reloads the page on the operator’s word', async () => {
    useUi.getState().markStaleAssets('tempo', [V2])
    const reload = vi.fn()

    render(<PluginAssetsBanner reload={reload} />)
    await userEvent.click(screen.getByRole('button', { name: 'reload' }))

    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('has no way to dismiss it: only the reload takes it down', () => {
    useUi.getState().markStaleAssets('tempo', [V2])

    render(<PluginAssetsBanner />)

    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.getByRole('button')).toHaveTextContent('reload')
  })
})

describe('useUi.markStaleAssets', () => {
  afterEach(() => {
    useUi.setState({ staleAssets: {} })
  })

  it('merges a later finding for the same workflow in, and never clears', () => {
    const { markStaleAssets } = useUi.getState()

    markStaleAssets('tempo', [V2])
    markStaleAssets('tempo', [V2, '/plugins/tempo/static/other.js?v=1'])
    markStaleAssets('tempo', [])

    expect(useUi.getState().staleAssets).toEqual({
      tempo: [V2, '/plugins/tempo/static/other.js?v=1'],
    })
  })

  it('leaves the state untouched when nothing new is found', () => {
    const { markStaleAssets } = useUi.getState()
    markStaleAssets('tempo', [V2])
    const before = useUi.getState()

    markStaleAssets('tempo', [V2])

    expect(useUi.getState()).toBe(before)
  })
})
