/**
 * The attention surface outside the window: the tab title and the
 * desktop notification (`components/attention.ts`,
 * `docs/v1/10-frontend.md` §Attention).
 *
 * The rule the suite exists for is the one a naive implementation gets
 * wrong: **the first answer to the inbox notifies nothing.** A page
 * reloaded on a machine with nine open requests would otherwise raise
 * nine notifications for questions the operator already knew about.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { RequestView } from '../../api/gen/types.gen'
import { request } from '../../panes/__tests__/fixtures'
import { queryKeys } from '../../realtime/invalidate'
import { usePrefs } from '../../store/prefs'
import { BASE_TITLE, notificationBody, titleFor, useAttention } from '../attention'

let queryClient: QueryClient
let raised: { title: string; body: string | undefined }[]

/** A `Notification` constructor that records instead of notifying. */
function stubNotification(permission: NotificationPermission) {
  raised = []
  class Recorder {
    static permission = permission
    static requestPermission = vi.fn(() => Promise.resolve(permission))
    constructor(title: string, options?: { body?: string }) {
      raised.push({ title, body: options?.body })
    }
  }
  vi.stubGlobal('Notification', Recorder)
}

/** A component that is nothing but the hook. */
function Attention() {
  useAttention()
  return null
}

function draw(rows: readonly RequestView[]) {
  queryClient.setQueryData(queryKeys.inbox(), rows)
  return render(
    <QueryClientProvider client={queryClient}>
      <Attention />
    </QueryClientProvider>,
  )
}

const ASKED = request({ id: 41, prompt: 'Which package manager?', pending: true })
const AND_ANOTHER = request({
  id: 42,
  node: 'review',
  source: 'agent',
  kind: 'permission',
  prompt: 'permission: run the gate',
  pending: true,
})

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false, staleTime: Infinity } })
  usePrefs.setState({ notifications: false })
  document.title = BASE_TITLE
  stubNotification('granted')
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  document.title = BASE_TITLE
})

describe('the tab title', () => {
  it('prefixes the open-request count, and drops the prefix at zero', () => {
    expect(titleFor(0)).toBe('Athanore')
    expect(titleFor(1)).toBe('(1) Athanore')
    expect(titleFor(12)).toBe('(12) Athanore')
  })

  it('follows the inbox', async () => {
    draw([ASKED, AND_ANOTHER])
    await waitFor(() => {
      expect(document.title).toBe('(2) Athanore')
    })

    queryClient.setQueryData(queryKeys.inbox(), [ASKED])
    await waitFor(() => {
      expect(document.title).toBe('(1) Athanore')
    })

    queryClient.setQueryData(queryKeys.inbox(), [])
    await waitFor(() => {
      expect(document.title).toBe('Athanore')
    })
  })

  it('is restored when the app unmounts', async () => {
    const { unmount } = draw([ASKED])
    await waitFor(() => {
      expect(document.title).toBe('(1) Athanore')
    })

    unmount()
    expect(document.title).toBe('Athanore')
  })
})

describe('the desktop notification', () => {
  it('raises nothing for what was already open when the tab loaded', async () => {
    usePrefs.setState({ notifications: true })

    draw([ASKED, AND_ANOTHER])

    await waitFor(() => {
      expect(document.title).toBe('(2) Athanore')
    })
    expect(raised).toEqual([])
  })

  it('raises one for a request that arrived while the operator looked away', async () => {
    usePrefs.setState({ notifications: true })
    draw([ASKED])
    await waitFor(() => {
      expect(document.title).toBe('(1) Athanore')
    })

    queryClient.setQueryData(queryKeys.inbox(), [ASKED, AND_ANOTHER])

    await waitFor(() => {
      expect(raised).toHaveLength(1)
    })
    expect(raised[0]?.title).toBe('Athanore · permission')
    expect(raised[0]?.body).toBe(notificationBody(AND_ANOTHER))
  })

  it('raises nothing while the setting is off, which is its default', async () => {
    draw([ASKED])
    await waitFor(() => {
      expect(document.title).toBe('(1) Athanore')
    })

    queryClient.setQueryData(queryKeys.inbox(), [ASKED, AND_ANOTHER])

    await waitFor(() => {
      expect(document.title).toBe('(2) Athanore')
    })
    expect(raised).toEqual([])
  })

  it('raises nothing when the browser has not granted permission', async () => {
    stubNotification('default')
    usePrefs.setState({ notifications: true })
    draw([ASKED])
    await waitFor(() => {
      expect(document.title).toBe('(1) Athanore')
    })

    queryClient.setQueryData(queryKeys.inbox(), [ASKED, AND_ANOTHER])

    await waitFor(() => {
      expect(document.title).toBe('(2) Athanore')
    })
    expect(raised).toEqual([])
  })

  it('names the node and the question, which is what is worth reading', () => {
    expect(notificationBody(AND_ANOTHER)).toBe('review · permission: run the gate')
  })
})
