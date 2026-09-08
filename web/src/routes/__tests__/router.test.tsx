import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'

import type { AppSearch } from '../search'
import { listRunsApiRunsGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import { PREFS_STORAGE_KEY, usePrefs } from '../../store/prefs'
import { createAppRouter } from '../router'

type Router = ReturnType<typeof createAppRouter>

/**
 * The router, over a cache holding an empty run list.
 *
 * The shell reads `GET /api/runs` (T061), so it needs a query client;
 * seeding it keeps these tests about the route and off the network.
 */
function mount(url: string): Router {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [url] }))
  const queryClient = new QueryClient({
    defaultOptions: { queries: { staleTime: 5000, retry: false } },
  })
  queryClient.setQueryData(listRunsApiRunsGetQueryKey(), [])
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

/**
 * The search the route hands its component.
 *
 * `useSearch({from: '/'})` returns `match.search`, so this reads the same
 * field the components read — not the private `_strictSearch`, which the
 * app never sees and which was green here while the browser was not. The
 * DOM assertions beside it check the other half: that what arrived is
 * what rendered.
 */
function appSearch(router: Router): AppSearch | undefined {
  return router.state.matches.at(-1)?.search
}

describe('the one route', () => {
  beforeEach(() => {
    localStorage.removeItem(PREFS_STORAGE_KEY)
    usePrefs.setState({ listCollapsed: false })
  })

  it('round-trips every search key through the URL', async () => {
    const router = mount('/?run=01JD5X&pane=3&overlay=library&task=12')

    await screen.findByRole('banner')
    expect(appSearch(router)).toEqual({
      run: '01JD5X',
      pane: 3,
      overlay: 'library',
      task: 12,
    })
    expect(router.state.matches.at(-1)?.searchError).toBeUndefined()

    await router.navigate({
      to: '/',
      search: { run: 'a4c8', pane: 0, overlay: 'palette', task: 7 },
    })
    await waitFor(() => {
      expect(router.state.location.searchStr).toBe(
        '?run=a4c8&pane=0&overlay=palette&task=7',
      )
    })
    expect(appSearch(router)).toEqual({
      run: 'a4c8',
      pane: 0,
      overlay: 'palette',
      task: 7,
    })
  })

  it('shows the selected run in the pane bar', async () => {
    mount('/?run=01JD5X')

    expect(await screen.findByTestId('selected-run')).toHaveTextContent('01JD5X')
  })

  it('opens on a stale overlay without throwing, having dropped it', async () => {
    // A bookmark from a build that still had the CRT chrome (D71).
    const router = mount('/?overlay=crt&run=a4c8&pane=x')

    await screen.findByRole('banner')
    expect(router.state.matches.at(-1)?.searchError).toBeUndefined()
    expect(appSearch(router)).toEqual({ run: 'a4c8' })
    expect(await screen.findByTestId('selected-run')).toHaveTextContent('a4c8')
  })

  it.each([
    ['?run=', 'an empty value'],
    ['?run=%20', 'whitespace'],
    ['?run=123', 'a number'],
    ['?run=[1,2]', 'an array'],
    ['?run={"a":1}', 'an object'],
  ])('drops a %s ?run= (%s) before it can render', async (query) => {
    // Everything the query string carries is merged into `match.search`,
    // so a value the validator drops must be dropped from the parse
    // itself: an object reaching `{search.run}` is React's "objects are
    // not valid as a React child", which is the app white-screening.
    const router = mount(`/${query}`)

    await screen.findByRole('banner')
    expect(appSearch(router)).toEqual({})
    expect(screen.queryByTestId('selected-run')).toBeNull()
  })

  it('navigates from what it validated, not from what the URL carried', async () => {
    const router = mount('/?overlay=crt&bogus=1&run=a4c8&pane=two&task=0')

    await screen.findByRole('banner')
    await userEvent.click(screen.getByRole('button', { name: /palette/ }))

    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('?run=a4c8&overlay=palette')
    })
    expect(appSearch(router)).toEqual({ run: 'a4c8', overlay: 'palette' })
  })

  it('opens the palette on `?overlay=palette` and writes it away on esc', async () => {
    const router = mount('/?run=a4c8&overlay=palette')

    await screen.findByTestId('palette')
    await userEvent.keyboard('{Escape}')

    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('?run=a4c8')
    })
    expect(appSearch(router)).toEqual({ run: 'a4c8' })
    expect(screen.queryByTestId('palette')).toBeNull()
  })

  it('replaces the palette with the overlay a command opens', async () => {
    const router = mount('/?overlay=palette')

    await screen.findByTestId('palette')
    await userEvent.click(
      screen.getByRole('option', { name: /^open workflow library/ }),
    )

    await waitFor(() => {
      expect(router.state.location.searchStr).toBe('?overlay=library')
    })
  })

  it('sends a path that is not / back to /', async () => {
    const router = mount('/runs/a4c8')

    await waitFor(() => {
      expect(router.state.location.pathname).toBe('/')
    })
    await screen.findByRole('banner')
  })
})
