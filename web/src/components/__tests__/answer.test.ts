/**
 * What an answer's refusal reads as, and what the option buttons are
 * styled by (`components/answer.ts`).
 *
 * The 422 mapping is the one worth being strict about: `loc` is a path
 * into the answer (`athanore/requests/validators.py`) and RJSF's
 * `extraErrors` is that path spelled as nesting, so this is the join
 * between T030's careful paths and a message appearing under the field
 * that caused it.
 */
import { describe, expect, it } from 'vitest'

import {
  ALLOW_KINDS,
  answerFailure,
  DENY_KINDS,
  extraErrorsFrom,
  isConflict,
  optionClass,
  optionOfKind,
  optionTone,
} from '../answer'

describe('a refusal', () => {
  it('reads the wire’s one error shape', () => {
    const failure = answerFailure(
      { error: 'that request already has an answer', code: 'already_answered' },
      'fallback',
    )

    expect(failure.message).toBe('that request already has an answer')
    expect(failure.code).toBe('already_answered')
    expect(failure.errors).toEqual([])
  })

  it('keeps the per-field detail of a 422, and drops what is not one', () => {
    const failure = answerFailure(
      {
        error: 'validation failed',
        code: 'validation',
        errors: [
          { loc: ['branch'], msg: 'field required', type: 'missing' },
          'not an error entry',
        ],
      },
      'fallback',
    )

    expect(failure.errors).toEqual([
      { loc: ['branch'], msg: 'field required', type: 'missing' },
    ])
  })

  it('falls back rather than saying nothing after a failed POST', () => {
    expect(answerFailure(new Error(''), 'the answer was not recorded').message).toBe(
      'the answer was not recorded',
    )
    expect(answerFailure(undefined, 'the answer was not recorded').message).toBe(
      'the answer was not recorded',
    )
    expect(answerFailure(new Error('network down'), 'x').message).toBe('network down')
    // A body that arrived as a bare string, which is what a proxy in
    // front of the server answers with.
    expect(answerFailure('502 Bad Gateway', 'x').message).toBe('502 Bad Gateway')
    expect(answerFailure('   ', 'the answer was not recorded').message).toBe(
      'the answer was not recorded',
    )
  })

  it('calls exactly the two 409s a conflict', () => {
    const codes = ['already_answered', 'stale_request', 'validation', 'invalid_option']
    expect(
      codes.map((code) => isConflict(answerFailure({ error: 'x', code }, 'y'))),
    ).toEqual([true, true, false, false])

    // A refusal with no code at all is not a conflict: the panel says it
    // inline, where the operator can act on it.
    expect(isConflict(answerFailure(new Error('boom'), 'y'))).toBe(false)
  })
})

describe('a 422 onto the fields', () => {
  it('nests one error under the path its `loc` names', () => {
    expect(
      extraErrorsFrom([{ loc: ['branch'], msg: 'field required', type: 'missing' }]),
    ).toEqual({ branch: { __errors: ['field required'] } })
  })

  it('walks a nested path, array indices included', () => {
    expect(
      extraErrorsFrom([
        { loc: ['outer', 'inner', 0], msg: 'too short', type: 'string_too_short' },
      ]),
    ).toEqual({ outer: { inner: { 0: { __errors: ['too short'] } } } })
  })

  it('puts an error about the answer as a whole on the root', () => {
    expect(extraErrorsFrom([{ loc: [], msg: 'expected an object', type: 'type' }])).toEqual(
      { __errors: ['expected an object'] },
    )
  })

  it('keeps both messages when two land on one field', () => {
    expect(
      extraErrorsFrom([
        { loc: ['branch'], msg: 'field required', type: 'missing' },
        { loc: ['branch'], msg: 'must not be blank', type: 'value_error' },
      ]),
    ).toEqual({ branch: { __errors: ['field required', 'must not be blank'] } })
  })

  it('shares the branches of two paths that overlap', () => {
    expect(
      extraErrorsFrom([
        { loc: ['a', 'b'], msg: 'one', type: 't' },
        { loc: ['a', 'c'], msg: 'two', type: 't' },
      ]),
    ).toEqual({ a: { b: { __errors: ['one'] }, c: { __errors: ['two'] } } })
  })
})

describe('an option’s kind', () => {
  it('is accent for allow, destructive for reject, neutral otherwise', () => {
    expect(optionTone('allow_once')).toBe('accent')
    expect(optionTone('allow_always')).toBe('accent')
    expect(optionTone('reject_once')).toBe('destructive')
    expect(optionTone('reject_always')).toBe('destructive')
    // A `human_input(options=…)` choice carries no ACP kind, and a kind
    // from a later ACP is one this build has never heard of. Neither is
    // a reason to refuse to draw the button (05 §Policies).
    expect(optionTone(null)).toBe('neutral')
    expect(optionTone(undefined)).toBe('neutral')
    expect(optionTone('defer')).toBe('neutral')
  })

  it('gives each tone its own classes, and never a fill', () => {
    expect(optionClass('allow_once')).toContain('text-[var(--color-accent-200)]')
    expect(optionClass('reject_once')).toContain('text-status-fail')
    expect(optionClass('defer')).toContain('text-[var(--color-neutral-300)]')
    for (const kind of ['allow_once', 'reject_once', 'defer']) {
      expect(optionClass(kind)).toContain('border-')
    }
  })
})

describe('the option `a` and `d` pick', () => {
  /** The three the fake agent offers, in an order nothing may rely on. */
  const OPTIONS = [
    { option_id: 'r', name: 'Reject', kind: 'reject_once' },
    { option_id: 'aa', name: 'Always allow', kind: 'allow_always' },
    { option_id: 'a', name: 'Allow once', kind: 'allow_once' },
    { option_id: 'defer', name: 'Ask me later' },
  ]

  it('prefers `*_once`, whatever order the options arrived in', () => {
    // 20 §Findings: ACP leaves list order unspecified, and 05 §Policies
    // picks `allow_once` before `allow_always` so a keystroke answers
    // this call rather than installing a standing rule.
    expect(optionOfKind(OPTIONS, ALLOW_KINDS)?.option_id).toBe('a')
    expect(optionOfKind(OPTIONS, DENY_KINDS)?.option_id).toBe('r')
  })

  it('falls back to `*_always` when `*_once` is not offered', () => {
    const always = OPTIONS.filter((option) => option.kind !== 'allow_once')
    expect(optionOfKind(always, ALLOW_KINDS)?.option_id).toBe('aa')
  })

  it('finds nothing in a question that is neither allow nor deny', () => {
    const labels = [
      { option_id: 'main', name: 'main' },
      { option_id: 'next', name: 'next' },
    ]
    expect(optionOfKind(labels, ALLOW_KINDS)).toBeUndefined()
    expect(optionOfKind(labels, DENY_KINDS)).toBeUndefined()
    expect(optionOfKind(null, ALLOW_KINDS)).toBeUndefined()
    expect(optionOfKind(undefined, DENY_KINDS)).toBeUndefined()
  })
})
