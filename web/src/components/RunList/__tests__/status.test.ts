import { describe, expect, it } from 'vitest'

import type { RunStatus } from '../../../api/gen/types.gen'
import { statusTone, toneClass, tonePulses } from '../status'

describe('statusTone', () => {
  it.each<[RunStatus, string]>([
    ['queued', 'queued'],
    ['running', 'active'],
    ['paused', 'paused'],
    ['completed', 'ok'],
    ['failed', 'fail'],
    ['cancelled', 'muted'],
  ])('maps %s onto the %s row of 10 §Status colours', (status, tone) => {
    expect(statusTone(status, 0)).toBe(tone)
  })

  it('gives a run with open requests the gate colour, whatever its status', () => {
    // 10 §Attention: a run waiting on a person is at a gate.
    expect(statusTone('running', 1)).toBe('gate')
    expect(statusTone('paused', 3)).toBe('gate')
  })
})

describe('toneClass', () => {
  it.each([
    ['ok', 'text-status-ok'],
    ['active', 'text-status-active'],
    ['gate', 'text-status-gate'],
    ['queued', 'text-status-queued'],
    ['fail', 'text-status-fail'],
    ['muted', 'text-status-muted'],
    ['paused', 'text-status-paused'],
  ] as const)('gives %s the %s utility', (tone, className) => {
    expect(toneClass(tone)).toBe(className)
  })
})

describe('tonePulses', () => {
  it('pulses for the one tone whose treatment is a pulse', () => {
    expect(tonePulses('active')).toBe(true)
  })

  it.each(['ok', 'gate', 'queued', 'fail', 'muted', 'paused'] as const)(
    'leaves %s plain',
    (tone) => {
      expect(tonePulses(tone)).toBe(false)
    },
  )
})
