/**
 * `AppRoute`: the shell's callbacks, written into the URL
 * (`../AppRoute.tsx`).
 *
 * The route is the one place the app navigates from. The shell holds no
 * selection state of its own — "selection is the URL" — so each of these
 * callbacks is a search transformation and nothing else, and three of
 * them are transformations of **more than one key at once**, which is
 * the only interesting thing about them: written as two `navigate`
 * calls, the second would be updating a search the first had already
 * replaced.
 *
 * `App` is replaced with a probe that offers one button per callback.
 * What `App` does with them is `../../App.test.tsx`'s, and that they
 * reach the real component is `./router.test.tsx`'s; what is under test
 * here is the mapping, over every callback rather than over the two a
 * DOM path happens to reach.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createMemoryHistory } from '@tanstack/react-router'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { createAppRouter } from '../router'

/**
 * The shell, as a row of buttons: one per callback, each calling it with
 * the arguments the real caller would.
 */
vi.mock('../../App', () => ({
  default: (props: Record<string, ((...args: never[]) => void) | undefined>) => {
    const call = (name: string, ...args: unknown[]) => () => {
      ;(props[name] as ((...args: unknown[]) => void) | undefined)?.(...args)
    }
    return (
      <div>
        <button type="button" onClick={call('onSelectRun', 'cccc3333')}>
          select run
        </button>
        <button type="button" onClick={call('onSelectPane', 2)}>
          select pane
        </button>
        <button type="button" onClick={call('onOpenPalette')}>
          open palette
        </button>
        <button type="button" onClick={call('onFilterNode', 'qa')}>
          filter node
        </button>
        <button type="button" onClick={call('onFilterNode', undefined)}>
          clear node filter
        </button>
        <button type="button" onClick={call('onOpenNode', 'review', 1)}>
          open node
        </button>
        <button type="button" onClick={call('onOpenNode', 'review', undefined)}>
          open node without a pane
        </button>
        <button type="button" onClick={call('onOpenOverlay', 'library')}>
          open overlay
        </button>
        <button type="button" onClick={call('onOpenAction', 'gamedev:override')}>
          open action
        </button>
        <button type="button" onClick={call('onCloseOverlay')}>
          close overlay
        </button>
        <button type="button" onClick={call('onOpenTask', 405)}>
          open task
        </button>
        <button type="button" onClick={call('onFocusStream', 405, 2)}>
          focus stream
        </button>
        <button type="button" onClick={call('onFocusStream', 405, undefined)}>
          focus stream without a pane
        </button>
        <button type="button" onClick={call('onClearRun')}>
          clear run
        </button>
        <button type="button" onClick={call('onShowGlobal', 1)}>
          show global
        </button>
        <button type="button" onClick={call('onShowGlobal', undefined)}>
          leave global
        </button>
      </div>
    )
  },
}))

type Router = ReturnType<typeof createAppRouter>

/** The route at `url`, with a cache nothing here asks anything of. */
function mount(url: string): Router {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [url] }))
  render(
    <QueryClientProvider client={new QueryClient()}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  return router
}

/** Press `label` and wait for the URL it wrote. */
async function press(router: Router, label: string, expected: string) {
  await userEvent.click(await screen.findByRole('button', { name: label }))
  await waitFor(() => {
    expect(router.state.location.searchStr).toBe(expected)
  })
}

describe('the selection', () => {
  it('writes `?run=` and drops the node filter with it', async () => {
    // A node filter is one run's graph; carried to the next run it would
    // filter that run's log to a node it may not have.
    const router = mount('/?run=aaaa1111&node=engineering&pane=1')

    await press(router, 'select run', '?run=cccc3333&pane=1')
  })

  it('takes the narrow global screen down when a run is selected', async () => {
    // `↓` on the global screen selects a run, and selecting one is how
    // the middle stops showing the global panes and starts showing the
    // run's (D216, D218).
    const router = mount('/?pane=1&global=0')

    await press(router, 'select run', '?run=cccc3333&pane=1')
  })

  it('writes `?pane=` and leaves the rest of the search alone', async () => {
    const router = mount('/?run=aaaa1111&node=engineering')

    await press(router, 'select pane', '?run=aaaa1111&pane=2&node=engineering')
  })

  it('clears the selection, and what was about it, once a run is gone', async () => {
    // A selection that no longer exists would point the detail pane at a
    // 404, and `?node=` and `?task=` were about that run too.
    const router = mount('/?run=aaaa1111&pane=1&node=qa&task=405')

    await press(router, 'clear run', '?pane=1')
  })

  it('clears a stale `?global=` with the run, so leaving the detail is the list', async () => {
    // `?global=` beside `?run=` is inert (D218 (1)); left in place,
    // clearing the run would land on the global screen rather than the
    // list the narrow `←` and the swipe right promise (D218 (3)).
    const router = mount('/?run=aaaa1111&pane=1&global=0')

    await press(router, 'clear run', '?pane=1')
  })

  it('leaves `?global=` alone when the pane changes', async () => {
    const router = mount('/?global=0')

    await press(router, 'select pane', '?pane=2&global=0')
  })
})

describe('the narrow global screen', () => {
  it('writes `?global=` and touches nothing else', async () => {
    // One parameter carries the screen and its pane; `?pane=` is the
    // operator's attention and is where the next run opens (21 §Narrow
    // layout, D216, D218).
    const router = mount('/?pane=1')

    await press(router, 'show global', '?pane=1&global=1')
  })

  it('writes it away to leave, so back works on it', async () => {
    const router = mount('/?pane=1&global=1')

    await press(router, 'leave global', '?pane=1')
  })

  it('comes down when a graph row opens the log pane', async () => {
    // `onOpenNode` names a run pane by index, which means nothing on a
    // screen showing a different cycle.
    const router = mount('/?run=aaaa1111&pane=0&global=0')

    await press(router, 'open node', '?run=aaaa1111&pane=1&node=review')
  })

  it('comes down when the task drawer hands over to the agent pane', async () => {
    const router = mount('/?run=aaaa1111&overlay=task&task=404&pane=0&global=0')

    await press(router, 'focus stream', '?run=aaaa1111&pane=2&task=405')
  })
})

describe('the node filter', () => {
  it('writes `?node=`', async () => {
    const router = mount('/?run=aaaa1111')

    await press(router, 'filter node', '?run=aaaa1111&node=qa')
  })

  it('writes it away when the pane’s own control clears it', async () => {
    const router = mount('/?run=aaaa1111&node=engineering')

    await press(router, 'clear node filter', '?run=aaaa1111')
  })

  it('writes the node and the pane in one navigation', async () => {
    // 10 §Graph pane: clicking a graph row "jumps to the log pane
    // filtered to that node" — one move, not two racing ones.
    const router = mount('/?run=aaaa1111&pane=0')

    await press(router, 'open node', '?run=aaaa1111&pane=1&node=review')
  })

  it('leaves the pane where it is when the cycle has no log pane', async () => {
    const router = mount('/?run=aaaa1111&pane=0')

    await press(router, 'open node without a pane', '?run=aaaa1111&pane=0&node=review')
  })
})

describe('the overlays', () => {
  it('opens the palette', async () => {
    const router = mount('/?run=aaaa1111')

    await press(router, 'open palette', '?run=aaaa1111&overlay=palette')
  })

  it('opens one by name, replacing whatever was up', async () => {
    const router = mount('/?run=aaaa1111&overlay=palette')

    await press(router, 'open overlay', '?run=aaaa1111&overlay=library')
  })

  it('closes by writing the one parameter away, so back works on it', async () => {
    const router = mount('/?run=aaaa1111&overlay=library')

    await press(router, 'close overlay', '?run=aaaa1111')
  })

  it('opens a plugin action as `?overlay=action&action=`', async () => {
    // Which overlay is up and which action it is about are two facts,
    // and `?overlay=` can only carry the first (T070).
    const router = mount('/?run=aaaa1111&overlay=palette')

    await press(
      router,
      'open action',
      '?run=aaaa1111&overlay=action&action=gamedev%3Aoverride',
    )
  })

  it('clears `?action=` when the overlay closes', async () => {
    // The action overlay is the only thing that reads it — unlike
    // `?task=`, which outlives the drawer as the agent pane's attempt.
    const router = mount('/?run=aaaa1111&overlay=action&action=gamedev:override')

    await press(router, 'close overlay', '?run=aaaa1111')
  })

  it('opens the task drawer as the pair 10 §Layout names', async () => {
    const router = mount('/?run=aaaa1111')

    await press(router, 'open task', '?run=aaaa1111&overlay=task&task=405')
  })
})

describe('focus stream', () => {
  it('closes the drawer, keeps `?task=` and moves the cycle, in one go', async () => {
    const router = mount('/?run=aaaa1111&overlay=task&task=404&pane=0')

    await press(router, 'focus stream', '?run=aaaa1111&pane=2&task=405')
  })

  it('leaves the pane where it is when the cycle has no agent pane', async () => {
    const router = mount('/?run=aaaa1111&overlay=task&task=404&pane=0')

    await press(router, 'focus stream without a pane', '?run=aaaa1111&pane=0&task=405')
  })
})
