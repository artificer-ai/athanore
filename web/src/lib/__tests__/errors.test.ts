/**
 * `actionError`: what a refused request said, in the two shapes a
 * refusal actually arrives in (`lib/errors.ts`).
 *
 * The generated client throws the **parsed body** rather than an
 * `Error`, so every surface that prints a refusal — the run ops, the
 * pickers, the drawer's operations — reads both and assumes neither. The
 * fallback is the point of the last case: a toast that said nothing
 * after a failed POST would look like one that had succeeded.
 */
import { describe, expect, it } from 'vitest'

import { actionError } from '../errors'

const FALLBACK = 'the run could not be paused'

describe('actionError', () => {
  it('reads the API’s one error shape', () => {
    expect(actionError({ error: 'run is not running', code: 'conflict' }, FALLBACK)).toBe(
      'run is not running',
    )
  })

  it('reads an Error, which is what a transport failure is', () => {
    // The client throws a `TypeError` when the connection dropped: there
    // is no body to parse and no `error` key on it.
    expect(actionError(new TypeError('Failed to fetch'), FALLBACK)).toBe(
      'Failed to fetch',
    )
  })

  it('prefers the body’s own message to the Error it arrived as', () => {
    const refusal = Object.assign(new Error('Request failed'), {
      error: 'run is not running',
    })

    expect(actionError(refusal, FALLBACK)).toBe('run is not running')
  })

  it('reads a bare string', () => {
    expect(actionError('run is not running', FALLBACK)).toBe('run is not running')
  })

  it.each([
    ['null', null],
    ['undefined', undefined],
    ['an empty body', {}],
    ['an empty message', { error: '' }],
    ['a message that is not a string', { error: 42 }],
    ['an Error with no message', new Error('')],
    ['whitespace', '   '],
    ['a number', 500],
  ])('falls back for %s', (_case, thrown) => {
    expect(actionError(thrown, FALLBACK)).toBe(FALLBACK)
  })
})
