/**
 * `RequestPanel`: the mode decides the control, one POST records the
 * answer, and a 409 is a toast (`components/RequestPanel.tsx`,
 * `docs/v1/06-requests.md` §Service and §Surfaces).
 *
 * The suite asserts on **what went out on the wire** wherever it can:
 * `option_id` for an `options` request and `value` for a `text` or
 * `form` one is the request's own `mode` deciding (06 §Service), and a
 * panel that sent the wrong one would draw identically.
 *
 * The toast is mocked rather than rendered. What 10 §Components fixes is
 * that a 409 goes to the toast surface and not into the card; which
 * surface that is, and how it looks, is `components/ui/sonner.tsx`.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import type { RequestView } from '../../api/gen/types.gen'
import { useKeymap } from '../../keys'
import { request } from '../../panes/__tests__/fixtures'
import { RequestPanel } from '../RequestPanel'

const { toast } = vi.hoisted(() => ({ toast: vi.fn() }))
vi.mock('sonner', () => ({ toast, Toaster: () => null }))

let queryClient: QueryClient

/** One request the server answers `answer` to, and what went out. */
function stubAnswer(body: unknown, status = 200) {
  const sent: { url: string; method: string; body: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (req: Request) => {
      sent.push({
        url: req.url,
        method: req.method,
        body: req.body === null ? undefined : await req.clone().json(),
      })
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return sent
}

function draw(view: RequestView) {
  return render(
    <QueryClientProvider client={queryClient}>
      <RequestPanel request={view} />
    </QueryClientProvider>,
  )
}

/** A pending permission with the three options the fake agent offers. */
const PERMISSION = request({
  id: 13,
  source: 'agent',
  kind: 'permission',
  mode: 'options',
  prompt: 'permission: run the gate',
  options: [
    { option_id: 'allow_once', name: 'Allow once', kind: 'allow_once' },
    { option_id: 'allow_always', name: 'Allow for this session', kind: 'allow_always' },
    { option_id: 'reject_once', name: 'Reject', kind: 'reject_once' },
    { option_id: 'defer', name: 'Ask me later' },
  ],
  pending: true,
})

beforeEach(() => {
  queryClient = createAppQueryClient()
  queryClient.setDefaultOptions({ queries: { retry: false }, mutations: { retry: false } })
  toast.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/* -------------------------------------------------------------------- */
/* options                                                               */
/* -------------------------------------------------------------------- */

describe('an options request', () => {
  it('draws one outlined button per option, styled by its kind', () => {
    draw(PERMISSION)

    const options = screen.getAllByTestId('request-option')
    expect(options.map((option) => option.getAttribute('data-tone'))).toEqual([
      'accent',
      'accent',
      'destructive',
      'neutral',
    ])
    // 10 §Tokens → shadcn: accent is a border and a text colour, never a
    // fill, and the destructive option follows it so the group reads as
    // one set of controls.
    expect(options[0]?.className).toContain('text-[var(--color-accent-200)]')
    expect(options[2]?.className).toContain('text-status-fail')
    expect(options[3]?.className).toContain('text-[var(--color-neutral-300)]')
    for (const option of options) expect(option.className).toContain('border')
  })

  it('posts the option id the operator picked, and nothing else', async () => {
    const user = userEvent.setup()
    const sent = stubAnswer({ ...PERMISSION, pending: false, answer: 'allow_once' })

    draw(PERMISSION)
    await user.click(screen.getByRole('button', { name: 'Allow once' }))

    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(sent[0]?.method).toBe('POST')
    expect(sent[0]?.url).toContain('/api/requests/13/answer')
    expect(sent[0]?.body).toEqual({ option_id: 'allow_once' })
  })

  it('waits for the server rather than rewriting the card first', async () => {
    const user = userEvent.setup()
    let release: (value: Response) => void = () => undefined
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Promise<Response>((resolve) => {
            release = resolve
          }),
      ),
    )

    draw(PERMISSION)
    await user.click(screen.getByRole('button', { name: 'Reject' }))

    // Every option is disabled while the one POST is in flight: two
    // answers to one request is what the 409 exists to refuse (06).
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    })
    expect(screen.getByTestId('request-panel')).toHaveAttribute('aria-busy', 'true')

    release(
      new Response(JSON.stringify(PERMISSION), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
  })
})

/* -------------------------------------------------------------------- */
/* text                                                                  */
/* -------------------------------------------------------------------- */

describe('a text request', () => {
  const QUESTION = request({ id: 24, mode: 'text', prompt: 'which one?', pending: true })

  it('sends what was typed, as the value', async () => {
    const user = userEvent.setup()
    const sent = stubAnswer({ ...QUESTION, pending: false, answer: 'pnpm' })

    draw(QUESTION)
    await user.type(screen.getByTestId('request-text'), 'pnpm')
    await user.click(screen.getByTestId('request-send'))

    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(sent[0]?.body).toEqual({ value: 'pnpm' })
  })

  it('will not spend a request on an answer 06 §Service refuses', async () => {
    const user = userEvent.setup()
    const sent = stubAnswer({})

    draw(QUESTION)
    expect(screen.getByTestId('request-send')).toBeDisabled()

    // Whitespace alone is not a text answer (06 §Service).
    await user.type(screen.getByTestId('request-text'), '   ')
    expect(screen.getByTestId('request-send')).toBeDisabled()
    expect(sent).toEqual([])
  })
})

/* -------------------------------------------------------------------- */
/* form                                                                  */
/* -------------------------------------------------------------------- */

describe('a form request', () => {
  const ELICITATION = request({
    id: 14,
    source: 'agent',
    kind: 'elicitation',
    mode: 'form',
    prompt: 'Which branch should the work land on?',
    schema: {
      type: 'object',
      required: ['branch'],
      properties: { branch: { type: 'string', title: 'branch' } },
    },
    pending: true,
  })

  it('sends the object the form produced', async () => {
    const user = userEvent.setup()
    const sent = stubAnswer({ ...ELICITATION, pending: false })

    draw(ELICITATION)
    const branch = document.getElementById('request-14_branch')
    await user.type(branch!, 'feat/T064')
    await user.click(screen.getByTestId('action-form-submit'))

    await waitFor(() => {
      expect(sent).toHaveLength(1)
    })
    expect(sent[0]?.body).toEqual({ value: { branch: 'feat/T064' } })
  })

  it('puts a 422 on the field the server named', async () => {
    const user = userEvent.setup()
    stubAnswer(
      {
        error: 'answer does not match the requested schema',
        code: 'validation',
        errors: [{ loc: ['branch'], msg: 'no such branch', type: 'value_error' }],
      },
      422,
    )

    draw(ELICITATION)
    await user.type(document.getElementById('request-14_branch')!, 'nope')
    await user.click(screen.getByTestId('action-form-submit'))

    await waitFor(() => {
      expect(document.getElementById('request-14_branch__error')).toHaveTextContent(
        'no such branch',
      )
    })
    // A 422 is the operator's to correct, so it stays where they are.
    expect(toast).not.toHaveBeenCalled()
  })

  it('says so when a form request carries no schema to draw', () => {
    draw(request({ id: 15, mode: 'form', pending: true }))

    expect(screen.getByTestId('request-no-schema')).toHaveTextContent('no schema')
    expect(screen.queryByTestId('action-form')).not.toBeInTheDocument()
  })
})

/* -------------------------------------------------------------------- */
/* the refusals                                                          */
/* -------------------------------------------------------------------- */

describe('a refusal', () => {
  it('toasts a 409 and refetches, rather than overwriting silently', async () => {
    const user = userEvent.setup()
    stubAnswer(
      { error: 'request 13 already has an answer', code: 'already_answered' },
      409,
    )
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')

    draw(PERMISSION)
    await user.click(screen.getByRole('button', { name: 'Allow once' }))

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith('request 13 already has an answer')
    })
    // The card is about to be replaced by the server's own view of the
    // request, so the message is not also left under the controls.
    expect(screen.queryByTestId('request-error')).not.toBeInTheDocument()
    expect(invalidate).toHaveBeenCalled()
  })

  it('toasts a stale request for the same reason', async () => {
    const user = userEvent.setup()
    stubAnswer(
      { error: 'the attempt that asked request 13 has ended', code: 'stale_request' },
      409,
    )

    draw(PERMISSION)
    await user.click(screen.getByRole('button', { name: 'Allow once' }))

    await waitFor(() => {
      expect(toast).toHaveBeenCalledWith(
        'the attempt that asked request 13 has ended',
      )
    })
  })

  it('says an option the request does not offer inline, where it can be acted on', async () => {
    const user = userEvent.setup()
    stubAnswer({ error: 'request 13 does not offer allow_once', code: 'invalid_option' }, 400)

    draw(PERMISSION)
    await user.click(screen.getByRole('button', { name: 'Allow once' }))

    expect(await screen.findByTestId('request-error')).toHaveTextContent(
      'request 13 does not offer allow_once',
    )
    expect(toast).not.toHaveBeenCalled()
  })

  it('never leaves a failed POST looking like an answer', async () => {
    const user = userEvent.setup()
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('Failed to fetch'))),
    )

    draw(PERMISSION)
    await user.click(screen.getByRole('button', { name: 'Allow once' }))

    expect(await screen.findByTestId('request-error')).toHaveTextContent(
      'Failed to fetch',
    )
  })
})

/* -------------------------------------------------------------------- */
/* `a` and `d`                                                           */
/* -------------------------------------------------------------------- */

/**
 * The panel under the app's one keyboard listener, with a control
 * outside it to press the same keys from.
 *
 * The real map is mounted rather than a stand-in: what 10 §Keyboard
 * fixes is that `a` and `d` are live "when the request panel has focus"
 * and dead everywhere else (D51), and only the real handler decides
 * that.
 */
function underTheKeymap(view: RequestView) {
  function Harness() {
    useKeymap({
      actions: [],
      select: () => {},
      cyclePane: () => {},
      jumpPane: () => {},
      runFocused: false,
      toggleRunFocus: () => {},
      moveRun: () => {},
      openPalette: () => {},
      close: () => {},
    })

    return (
      <>
        <input aria-label="filter runs" />
        <section aria-label="runs" data-region="list">
          <button type="button">a run row</button>
        </section>
        <RequestPanel request={view} />
      </>
    )
  }

  return render(
    <QueryClientProvider client={queryClient}>
      <Harness />
    </QueryClientProvider>,
  )
}

describe('the request panel’s two keys', () => {
  it('answers `allow_once` on `a`, from inside the panel', async () => {
    const sent = stubAnswer({ ok: true })
    underTheKeymap(PERMISSION)

    fireEvent.keyDown(screen.getByRole('button', { name: 'Allow once' }), { key: 'a' })

    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]?.method).toBe('POST')
    expect(sent[0]?.url).toContain('/api/requests/13/answer')
    expect(sent[0]?.body).toEqual({ option_id: 'allow_once' })
  })

  it('answers `reject_once` on `d`', async () => {
    const sent = stubAnswer({ ok: true })
    underTheKeymap(PERMISSION)

    fireEvent.keyDown(screen.getByTestId('request-panel'), { key: 'd' })

    await waitFor(() => expect(sent).toHaveLength(1))
    expect(sent[0]?.body).toEqual({ option_id: 'reject_once' })
  })

  it('does nothing from the run list, and nothing from an input', async () => {
    const sent = stubAnswer({ ok: true })
    underTheKeymap(PERMISSION)

    fireEvent.keyDown(screen.getByRole('button', { name: 'a run row' }), { key: 'a' })
    fireEvent.keyDown(screen.getByRole('region', { name: 'runs' }), { key: 'd' })
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'filter runs' }), { key: 'a' })

    // Nothing to wait for: the assertion is that no POST was made, and a
    // flush of the microtask queue is enough to see one that was.
    await Promise.resolve()
    expect(sent).toEqual([])
  })

  it('has no key for a question that is not allow or deny', async () => {
    const sent = stubAnswer({ ok: true })
    // A `human_input` choice: labels, no ACP kinds (06 §The model).
    underTheKeymap(
      request({
        id: 21,
        source: 'node',
        kind: 'question',
        mode: 'options',
        prompt: 'which branch?',
        options: [
          { option_id: 'main', name: 'main' },
          { option_id: 'next', name: 'next' },
        ],
        pending: true,
      }),
    )

    fireEvent.keyDown(screen.getByTestId('request-panel'), { key: 'a' })
    fireEvent.keyDown(screen.getByTestId('request-panel'), { key: 'd' })

    await Promise.resolve()
    expect(sent).toEqual([])
  })

  it('has no key for a text request, whose keystrokes are its answer', async () => {
    const sent = stubAnswer({ ok: true })
    underTheKeymap(
      request({
        id: 22,
        source: 'node',
        kind: 'question',
        mode: 'text',
        prompt: 'which branch?',
        pending: true,
      }),
    )

    fireEvent.keyDown(screen.getByTestId('request-panel'), { key: 'a' })

    await Promise.resolve()
    expect(sent).toEqual([])
  })
})
