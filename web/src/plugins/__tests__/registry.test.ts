/**
 * The element table (`../registry.ts`, `docs/v1/09-plugins.md` §Escape
 * hatch, §Builtins are plugins).
 *
 * What matters here is not that the three builtin tags draw — that is
 * `panes/__tests__/content.test.tsx`, through the dispatch a plugin's
 * tag takes — but that they are in the *same* table a plugin's tag is
 * looked up in, and that a tag with no entry answers `undefined` rather
 * than throwing. A host that could not be asked about a plugin's tag
 * would be a host with hard-coded pane knowledge, which is exactly what
 * 09 says the manifest exists to remove.
 */
import { describe, expect, it } from 'vitest'

import { elementRenderer, registerElement, registeredElements } from '../registry'

describe('the element table', () => {
  it('holds the three elements the core ships', () => {
    expect(registeredElements()).toEqual([
      'ath-agent-stream',
      'ath-requests',
      'ath-run-graph',
    ])
  })

  it('answers nothing for a tag this build does not draw', () => {
    expect(elementRenderer('gd-playfield')).toBeUndefined()
  })

  it('is the same table a plugin’s tag would be registered in', () => {
    const content = { node: null, scrolls: false }
    registerElement('gd-playfield', () => content)

    expect(elementRenderer('gd-playfield')?.({ scope: {} })).toBe(content)
    expect(registeredElements()).toContain('gd-playfield')
  })
})
