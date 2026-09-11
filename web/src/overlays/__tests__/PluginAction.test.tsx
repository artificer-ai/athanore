/**
 * `PluginAction`: the overlay a palette row for a plugin's action opens
 * (`overlays/PluginAction.tsx`).
 *
 * The form, the confirm and the POST are `ActionRunner`'s and are
 * asserted there. What is under test here is the overlay's own three
 * facts: the action `?action=` names is the one drawn, a name this
 * server does not carry is said plainly rather than drawn as an empty
 * form, and a call that landed closes it (D174 (4)).
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import { manifestApiPluginsGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import { MANIFEST } from '../../panes/__tests__/fixtures'
import { PluginAction, PLUGIN_ACTION_TITLE } from '../PluginAction'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

const RUN = '01JD5XPLUGINOVERLAY00000'

let queryClient: QueryClient

/**
 * Answer the action's POST with `body`, and every read with the manifest.
 *
 * The seeded cache below is refetched in the background, so a stub that
 * answered `GET /api/plugins` with the action's result would replace the
 * manifest with something that is not one — and the overlay would
 * correctly report that this server declares no such action.
 */
function stubServer(body: unknown, status = 200) {
  const sent: { url: string; method: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      sent.push({ url: request.url, method: request.method })
      const answer = request.method === 'POST' ? { body, status } : { body: MANIFEST, status: 200 }
      return new Response(JSON.stringify(answer.body), {
        status: answer.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return sent
}

function draw(action: string | undefined, onClose = vi.fn()) {
  render(
    <QueryClientProvider client={queryClient}>
      <PluginAction
        open
        action={action}
        runId={RUN}
        taskId={undefined}
        onClose={onClose}
      />
    </QueryClientProvider>,
  )
  return onClose
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false } })
  queryClient.setQueryData(manifestApiPluginsGetQueryKey(), MANIFEST)
  toast.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

it('draws the action the search names, with its own form', async () => {
  stubServer({ ok: true })

  draw('gamedev:override')

  const panel = await screen.findByTestId('plugin-action')
  expect(panel).toHaveAccessibleName(PLUGIN_ACTION_TITLE)
  expect(screen.getByTestId('overlay-gloss')).toHaveTextContent('gamedev · override')
  expect(await screen.findByTestId('action-runner')).toHaveAttribute(
    'data-action',
    'override',
  )
  expect(document.getElementById('action-gamedev-override_word')).toBeInTheDocument()
})

it('says so for an action this server does not declare', async () => {
  stubServer({ ok: true })

  draw('gamedev:ghost')

  expect(await screen.findByTestId('plugin-action-notice')).toHaveTextContent(
    'this server declares no action ghost on gamedev',
  )
})

it('says so for a search that names no action at all', async () => {
  stubServer({ ok: true })

  draw(undefined)

  expect(await screen.findByTestId('plugin-action-notice')).toHaveTextContent(
    'pick an action from the palette',
  )
})

it('closes once the call has landed', async () => {
  const user = userEvent.setup()
  stubServer({ ok: true })

  const onClose = draw('gamedev:reseed')

  // `reseed` is `global`-scoped and declares no model, so the form is
  // its submit button and there is no confirm in front of it.
  await user.click(await screen.findByTestId('action-form-submit'))

  await waitFor(() => {
    expect(onClose).toHaveBeenCalledTimes(1)
  })
  expect(toast).toHaveBeenCalledWith('Reseed the dictionary · done')
})

describe('a scope the selection cannot resolve', () => {
  it('says what it is waiting for rather than posting', async () => {
    const sent = stubServer({ ok: true })

    render(
      <QueryClientProvider client={queryClient}>
        <PluginAction
          open
          action="gamedev:flag"
          runId={RUN}
          taskId={undefined}
          onClose={vi.fn()}
        />
      </QueryClientProvider>,
    )

    expect(await screen.findByTestId('action-waiting')).toHaveTextContent(
      'focus an attempt',
    )
    expect(sent.filter((one) => one.method === 'POST')).toEqual([])
  })
})
