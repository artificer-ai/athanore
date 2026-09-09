/**
 * `ActionRunner`: the form, the confirm, and the one POST
 * (`components/ActionRunner.tsx`, `docs/v1/09-plugins.md` §Declarations,
 * §Wire contract).
 *
 * The suite asserts on **what went out on the wire**, because that is
 * where the rules live: `confirm=true` means nothing was sent until the
 * dialog was answered, and cancelling means nothing was sent at all. A
 * runner that drew the dialog and posted anyway would look identical on
 * screen.
 *
 * The toast is mocked rather than rendered, as `RequestPanel.test.tsx`
 * mocks it: what 10 §Components fixes is that a landed call reports on
 * the toast surface, not what that surface looks like.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { ActionOut, ActionScope } from '../../api/gen/types.gen'
import { GAMEDEV_ENTRY } from '../../panes/__tests__/fixtures'
import { ActionRunner } from '../ActionRunner'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

const RUN = '01JD5XRUNNER000000000000'
const PREFIX = 'panel-gamedev-override'

const OVERRIDE = GAMEDEV_ENTRY.actions?.[0] as ActionOut
const RESEED = GAMEDEV_ENTRY.actions?.[2] as ActionOut

let queryClient: QueryClient

/** Answer the POST with `body`, and record what was sent. */
function stubPost(body: unknown, status = 200) {
  const sent: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      sent.push({
        url: request.url,
        method: request.method,
        body: request.body === null ? undefined : await request.clone().json(),
      })
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return sent
}

function draw(
  entry: ActionOut,
  invocation: ActionScope | null = { run_id: RUN },
  onDone = vi.fn(),
) {
  render(
    <QueryClientProvider client={queryClient}>
      <ActionRunner
        workflow="gamedev"
        action={entry}
        invocation={invocation}
        idPrefix={PREFIX}
        onDone={onDone}
      />
    </QueryClientProvider>,
  )
  return onDone
}

/** The input RJSF gave the field at `path`. */
function field(path: string): HTMLElement {
  const element = document.getElementById(`${PREFIX}_${path}`)
  if (element === null) throw new Error(`no field ${path}`)
  return element
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false } })
  toast.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('the confirm flow', () => {
  it('asks before it posts, and cancelling posts nothing', async () => {
    const user = userEvent.setup()
    const sent = stubPost({ ok: true })

    draw(OVERRIDE)

    await user.type(field('word'), 'crucible')
    await user.click(screen.getByTestId('action-form-submit'))

    // The dialog is up and the endpoint has not been reached: `confirm`
    // is asked *before* the call, which is the whole of what it means.
    expect(await screen.findByTestId('action-confirm')).toBeInTheDocument()
    expect(sent).toEqual([])

    await user.click(screen.getByTestId('action-confirm-cancel'))

    await waitFor(() => {
      expect(screen.queryByTestId('action-confirm')).not.toBeInTheDocument()
    })
    expect(sent).toEqual([])
    expect(toast).not.toHaveBeenCalled()
  })

  it('names what the call would run on', async () => {
    const user = userEvent.setup()
    stubPost({ ok: true })

    draw(OVERRIDE, { run_id: RUN, task_id: 12 })

    await user.type(field('word'), 'crucible')
    await user.click(screen.getByTestId('action-form-submit'))

    expect(await screen.findByTestId('action-confirm-target')).toHaveTextContent(
      `run ${RUN} · attempt 12`,
    )
  })

  it('posts the scope and the value once confirmed', async () => {
    const user = userEvent.setup()
    const sent = stubPost({ word: 'crucible' })
    const onDone = draw(OVERRIDE)

    await user.type(field('word'), 'crucible')
    await user.click(screen.getByTestId('action-form-submit'))
    await user.click(await screen.findByTestId('action-confirm-run'))

    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(sent[0]?.method).toBe('POST')
    expect(sent[0]?.url).toBe(
      `${window.location.origin}/api/plugins/gamedev/actions/override`,
    )
    expect(sent[0]?.body).toEqual({
      scope: { run_id: RUN },
      input: { word: 'crucible', reason: '' },
    })
    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith('Override secret word · done')
    })
    expect(onDone).toHaveBeenCalledTimes(1)
  })

  it('does not ask for an action that did not declare it', async () => {
    const user = userEvent.setup()
    const sent = stubPost('the dictionary was reseeded')

    draw(RESEED, {})

    // No fields at all: 09's action with no model is a form with nothing
    // but its submit button, and it posts straight away.
    await user.click(screen.getByTestId('action-form-submit'))

    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(screen.queryByTestId('action-confirm')).not.toBeInTheDocument()
    expect(sent[0]?.body).toEqual({ scope: {}, input: {} })
    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        'Reseed the dictionary · the dictionary was reseeded',
      )
    })
  })
})

describe('what the server said', () => {
  it('lands a 422 on the field that caused it', async () => {
    const user = userEvent.setup()
    stubPost(
      {
        error: 'validation failed',
        code: 'validation',
        errors: [{ loc: ['word'], msg: 'that word is already taken', type: 'value_error' }],
      },
      422,
    )

    draw(OVERRIDE)

    await user.type(field('word'), 'crucible')
    await user.click(screen.getByTestId('action-form-submit'))
    await user.click(await screen.findByTestId('action-confirm-run'))

    // Beside the field, by the id RJSF built for it, and once above the
    // form as well — a `loc` naming something the schema does not draw
    // must not disappear (D168 (2)).
    await waitFor(() => {
      expect(document.getElementById(`${PREFIX}_word__error`)).toHaveTextContent(
        'that word is already taken',
      )
    })
    expect(screen.getByTestId('action-form-message')).toHaveTextContent(
      'validation failed',
    )
    expect(toast).not.toHaveBeenCalled()
  })

  it('draws any other refusal above the form, and does not close', async () => {
    const user = userEvent.setup()
    const onDone = vi.fn()
    stubPost({ error: 'the word has already been overridden', code: 'plugin_error' }, 409)

    draw(OVERRIDE, { run_id: RUN }, onDone)

    await user.type(field('word'), 'crucible')
    await user.click(screen.getByTestId('action-form-submit'))
    await user.click(await screen.findByTestId('action-confirm-run'))

    expect(await screen.findByTestId('action-form-message')).toHaveTextContent(
      'the word has already been overridden',
    )
    expect(onDone).not.toHaveBeenCalled()
  })
})

describe('a scope it cannot resolve', () => {
  it('says what it is waiting for instead of drawing a form', () => {
    const sent = stubPost({})

    draw(OVERRIDE, null)

    expect(screen.getByTestId('action-waiting')).toHaveTextContent(
      'select a run to run this action',
    )
    expect(screen.queryByTestId('action-form')).not.toBeInTheDocument()
    expect(sent).toEqual([])
  })
})
