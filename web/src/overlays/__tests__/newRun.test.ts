/**
 * `newRun.ts`: the shape a submission has to fit and the two calls that
 * make one (`overlays/newRun.ts`, `docs/v1/10-frontend.md` §Overlays,
 * D34, D57).
 *
 * The wire assertions live here rather than only in the component suite
 * because "top is two calls and bottom is one" is the whole of D57 and
 * neither shape is visible on screen: an overlay that never posted the
 * move would look exactly like one that did.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { client } from '../../api/gen/client.gen'
import {
  isNewRunFailure,
  newRunSchema,
  POSITION_FALLBACK,
  SUBMIT_FALLBACK,
  submitNewRun,
  TOP_INDEX,
  type NewRunValues,
} from '../newRun'

client.setConfig({ baseUrl: '' })

/** What went out, in order, and what the server answered to each. */
function stub(...responses: { status: number; body: unknown }[]) {
  const sent: { url: string; method: string; body: unknown }[] = []
  let call = 0

  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      sent.push({
        url: request.url,
        method: request.method,
        body: request.body === null ? undefined : await request.clone().json(),
      })
      const answer = responses[call++] ?? { status: 200, body: {} }
      return new Response(JSON.stringify(answer.body), {
        status: answer.status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  return sent
}

const VALUES: NewRunValues = {
  workflow: 'feature_build',
  title: 'port the settings module',
  description: 'see docs/v1/11-settings.md',
  position: 'bottom',
}

const CREATED = { status: 201, body: { run_id: '01JRUN' } }

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('newRunSchema', () => {
  it('strips the title, as the server does', () => {
    const parsed = newRunSchema.parse({ ...VALUES, title: '  a title  ' })

    expect(parsed.title).toBe('a title')
  })

  it('refuses a title that is nothing but whitespace', () => {
    const parsed = newRunSchema.safeParse({ ...VALUES, title: '   ' })

    expect(parsed.success).toBe(false)
  })

  it('accepts an empty description: the workflow may need no input', () => {
    expect(newRunSchema.safeParse({ ...VALUES, description: '' }).success).toBe(true)
  })

  it('accepts only the two positions of D34', () => {
    expect(newRunSchema.safeParse({ ...VALUES, position: 'top' }).success).toBe(true)
    expect(newRunSchema.safeParse({ ...VALUES, position: 'middle' }).success).toBe(false)
  })
})

describe('submitNewRun', () => {
  it('queues the run and stops there for `bottom`', async () => {
    const sent = stub(CREATED)

    await expect(submitNewRun(VALUES)).resolves.toBe('01JRUN')

    expect(sent).toHaveLength(1)
    expect(sent[0]?.method).toBe('POST')
    expect(sent[0]?.url).toContain('/api/workflows/feature_build/runs')
    expect(sent[0]?.body).toEqual({
      title: 'port the settings module',
      description: 'see docs/v1/11-settings.md',
    })
  })

  it('moves the run it queued to index 0 for `top` (D57)', async () => {
    const sent = stub(CREATED, { status: 200, body: { position: 1 } })

    await expect(submitNewRun({ ...VALUES, position: 'top' })).resolves.toBe('01JRUN')

    expect(sent).toHaveLength(2)
    expect(sent[1]?.method).toBe('POST')
    expect(sent[1]?.url).toContain('/api/runs/01JRUN/position')
    expect(sent[1]?.body).toEqual({ index: TOP_INDEX })
    expect(TOP_INDEX).toBe(0)
  })

  it('carries a refused submission out, with nothing queued', async () => {
    stub({ status: 409, body: { error: 'no workflow named feature_build' } })

    const failure = await submitNewRun(VALUES).catch((error: unknown) => error)

    expect(isNewRunFailure(failure)).toBe(true)
    expect(failure).toEqual({
      message: 'no workflow named feature_build',
      queued: undefined,
    })
  })

  it('names the run it queued when the move that followed failed', async () => {
    stub(CREATED, { status: 422, body: { error: 'index must be an integer' } })

    const failure = await submitNewRun({ ...VALUES, position: 'top' }).catch(
      (error: unknown) => error,
    )

    expect(failure).toEqual({ message: 'index must be an integer', queued: '01JRUN' })
  })

  it('says something of its own when a refusal carried no message', async () => {
    stub({ status: 500, body: {} })

    await expect(submitNewRun(VALUES)).rejects.toMatchObject({
      message: SUBMIT_FALLBACK,
    })
  })

  it('...and something else when the move is the call that failed', async () => {
    stub(CREATED, { status: 500, body: {} })

    await expect(submitNewRun({ ...VALUES, position: 'top' })).rejects.toMatchObject({
      message: POSITION_FALLBACK,
      queued: '01JRUN',
    })
  })
})

describe('isNewRunFailure', () => {
  it('holds only for the shape this module throws', () => {
    expect(isNewRunFailure({ message: 'no', queued: undefined })).toBe(true)
    expect(isNewRunFailure({ message: 'no', queued: '01JRUN' })).toBe(true)
    expect(isNewRunFailure(new Error('boom'))).toBe(false)
    expect(isNewRunFailure({ error: 'boom' })).toBe(false)
    expect(isNewRunFailure(null)).toBe(false)
  })
})
