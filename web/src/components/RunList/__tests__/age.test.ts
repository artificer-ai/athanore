import { describe, expect, it } from 'vitest'

import { UNKNOWN_AGE, humaniseAge } from '../age'

/** 2026-09-08T09:00:00Z, the instant every case below is measured from. */
const NOW = Date.parse('2026-09-08T09:00:00Z')

function ago(ms: number): string {
  return new Date(NOW - ms).toISOString()
}

const SECOND = 1000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

describe('humaniseAge', () => {
  it.each([
    [0, '0s'],
    [42 * SECOND, '42s'],
    [59 * SECOND + 999, '59s'],
    [MINUTE, '1m'],
    [4 * MINUTE, '4m'],
    [55 * MINUTE, '55m'],
    [HOUR, '1.0h'],
    [15.3 * HOUR, '15.3h'],
    [DAY, '1.0d'],
    [16.7 * DAY, '16.7d'],
  ])('writes %d ms ago as %s', (elapsed, expected) => {
    expect(humaniseAge(ago(elapsed), NOW)).toBe(expected)
  })

  it('reads a timestamp ahead of this clock as no age at all', () => {
    // A browser a second ahead of the server is ordinary; `-1s` would
    // say something about the data that is not true.
    expect(humaniseAge(new Date(NOW + 5 * SECOND).toISOString(), NOW)).toBe('0s')
  })

  it('omits an age it cannot compute rather than guessing one', () => {
    expect(humaniseAge('not a timestamp', NOW)).toBe(UNKNOWN_AGE)
  })
})
