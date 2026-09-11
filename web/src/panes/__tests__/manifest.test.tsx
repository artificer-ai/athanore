/**
 * `useManifest` noticing what this document cannot follow
 * (`../manifest.ts`, 22 §SPA).
 *
 * The check runs at manifest load — not only when a custom pane mounts —
 * so a pane the operator viewed and cycled away from still raises the
 * notice when its workflow is reloaded with new JavaScript. What is
 * asserted is the store the banner reads: which workflows, which URLs,
 * and that a first load, an identical refetch and a removal write
 * nothing.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { manifestApiPluginsGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import type { PluginManifestEntry } from '../../api/gen/types.gen'
import { ASSET_ATTRIBUTE, injectAssets } from '../../plugins'
import { useUi } from '../../store/ui'
import { useManifest } from '../manifest'
import { BUILTIN_ENTRY, GAMEDEV_ENTRY } from './fixtures'

const PATH = '/plugins/gamedev/static/playfield.js'
const V1 = `${PATH}?v=aaaaaaaaaaaa`
const V2 = `${PATH}?v=bbbbbbbbbbbb`

/** `gamedev` as a served manifest lists it: its asset at a version. */
function gamedev(assets: string[]): PluginManifestEntry {
  return { ...GAMEDEV_ENTRY, assets }
}

/** The reader, showing what it read so a test can wait for a refetch. */
function Host() {
  const { manifest } = useManifest()
  return (
    <span data-testid="assets">
      {manifest.flatMap((entry) => entry.assets ?? []).join(' ')}
    </span>
  )
}

let queryClient: QueryClient

/** Render the reader over a manifest, and return a way to replace it. */
function load(manifest: PluginManifestEntry[]) {
  queryClient.setQueryData(manifestApiPluginsGetQueryKey(), manifest)
  render(
    <QueryClientProvider client={queryClient}>
      <Host />
    </QueryClientProvider>,
  )
  // The cache notifies its observers on a timer, so a replacement is
  // waited for by what the reader draws of it.
  return async (next: PluginManifestEntry[]) => {
    act(() => {
      queryClient.setQueryData(manifestApiPluginsGetQueryKey(), next)
    })
    await waitFor(() => {
      expect(screen.getByTestId('assets')).toHaveTextContent(
        next.flatMap((entry) => entry.assets ?? []).join(' '),
        { normalizeWhitespace: true },
      )
    })
  }
}

beforeEach(() => {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(() => {
  for (const script of document.head.querySelectorAll(`script[${ASSET_ATTRIBUTE}]`)) {
    script.remove()
  }
  useUi.setState({ staleAssets: {} })
})

describe('useManifest and the document’s assets', () => {
  it('marks nothing on a first load', () => {
    load([BUILTIN_ENTRY, gamedev([V1])])

    expect(useUi.getState().staleAssets).toEqual({})
  })

  it('marks nothing on a refetch that lists what is loaded', async () => {
    const refetch = load([BUILTIN_ENTRY, gamedev([V1])])
    injectAssets([V1])

    await refetch([BUILTIN_ENTRY, gamedev([V1])])

    expect(useUi.getState().staleAssets).toEqual({})
  })

  it('marks the workflow whose asset moved to a new ?v= under a loaded one', async () => {
    const refetch = load([BUILTIN_ENTRY, gamedev([V1])])
    injectAssets([V1])

    await refetch([BUILTIN_ENTRY, gamedev([V2])])

    expect(useUi.getState().staleAssets).toEqual({ gamedev: [V2] })
  })

  it('marks nothing when the workflow is removed', async () => {
    const refetch = load([BUILTIN_ENTRY, gamedev([V1])])
    injectAssets([V1])

    await refetch([BUILTIN_ENTRY])

    expect(useUi.getState().staleAssets).toEqual({})
  })

  it('marks nothing for a workflow whose pane was never opened', async () => {
    // Nothing of it was injected, so the new version is simply what the
    // pane will inject when it first mounts.
    const refetch = load([BUILTIN_ENTRY, gamedev([V1])])

    await refetch([BUILTIN_ENTRY, gamedev([V2])])

    expect(useUi.getState().staleAssets).toEqual({})
  })

  it('keeps what it marked once the workflow moves on again', async () => {
    // The store is never cleared: the document is what is stale, and
    // only a reload makes a new one (D253).
    const refetch = load([BUILTIN_ENTRY, gamedev([V1])])
    injectAssets([V1])

    await refetch([BUILTIN_ENTRY, gamedev([V2])])
    await refetch([BUILTIN_ENTRY])
    await refetch([BUILTIN_ENTRY, gamedev([V1])])

    expect(useUi.getState().staleAssets).toEqual({ gamedev: [V2] })
  })
})
