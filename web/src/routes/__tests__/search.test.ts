import { describe, expect, it } from 'vitest'

import { OVERLAYS, validateAppSearch } from '../search'

describe('validateAppSearch', () => {
  it('keeps every key it recognises', () => {
    expect(
      validateAppSearch({
        run: '01JD5',
        pane: 2,
        overlay: 'palette',
        task: 7,
        node: 'engineering',
      }),
    ).toEqual({
      run: '01JD5',
      pane: 2,
      overlay: 'palette',
      task: 7,
      node: 'engineering',
    })
  })

  it('accepts every overlay of 10 §Overlays', () => {
    for (const overlay of OVERLAYS) {
      expect(validateAppSearch({ overlay })).toEqual({ overlay })
    }
  })

  it('drops an unknown overlay rather than throwing', () => {
    // A bookmark from a build that still had the CRT chrome (D71).
    expect(() => validateAppSearch({ overlay: 'crt' })).not.toThrow()
    expect(validateAppSearch({ overlay: 'crt', run: 'a4c8' })).toEqual({ run: 'a4c8' })
    expect(validateAppSearch({ overlay: 3 })).toEqual({})
    expect(validateAppSearch({ overlay: '' })).toEqual({})
  })

  it('parses numeric keys out of strings, as a hand-typed URL gives them', () => {
    expect(validateAppSearch({ pane: '4', task: '12' })).toEqual({ pane: 4, task: 12 })
  })

  it('drops numbers that are not indices', () => {
    expect(validateAppSearch({ pane: -1 })).toEqual({})
    expect(validateAppSearch({ pane: 1.5 })).toEqual({})
    expect(validateAppSearch({ pane: 'two' })).toEqual({})
    expect(validateAppSearch({ pane: '' })).toEqual({})
    expect(validateAppSearch({ pane: Number.NaN })).toEqual({})
    // Task ids start at 1.
    expect(validateAppSearch({ task: 0 })).toEqual({})
    expect(validateAppSearch({ task: -3 })).toEqual({})
  })

  it('drops a run id that is not a non-empty string', () => {
    expect(validateAppSearch({ run: '' })).toEqual({})
    expect(validateAppSearch({ run: '   ' })).toEqual({})
    expect(validateAppSearch({ run: 42 })).toEqual({})
  })

  it('drops a node filter that is not a non-empty string', () => {
    expect(validateAppSearch({ node: '' })).toEqual({})
    expect(validateAppSearch({ node: '   ' })).toEqual({})
    expect(validateAppSearch({ node: 3 })).toEqual({})
  })

  it('ignores keys it does not know', () => {
    expect(validateAppSearch({ crt: true, priority: 4 })).toEqual({})
  })

  it('drops nothing when the search is empty', () => {
    expect(validateAppSearch({})).toEqual({})
  })
})
