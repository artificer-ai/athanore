/**
 * Injecting a plugin's JavaScript (`../assets.ts`, `docs/v1/09-plugins.md`
 * §Escape hatch).
 *
 * "The SPA injects them once as `<script type="module">`" is two claims,
 * and the second is the one with teeth: a module cannot be un-executed,
 * so a second `<script>` for one URL would run the plugin's
 * `customElements.define` a second time and throw.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ASSET_ATTRIBUTE, assetLoaded, injectAssets, injectedAssets } from '../assets'

const PLAYFIELD = '/plugins/gamedev/static/playfield.js'
const HELPER = '/plugins/gamedev/static/vendor/helper.js'

afterEach(() => {
  for (const script of document.head.querySelectorAll(`script[${ASSET_ATTRIBUTE}]`)) {
    script.remove()
  }
  vi.restoreAllMocks()
})

it('injects each url as a same-origin module script', () => {
  injectAssets([PLAYFIELD, HELPER])

  const scripts = [
    ...document.head.querySelectorAll<HTMLScriptElement>(`script[${ASSET_ATTRIBUTE}]`),
  ]
  expect(scripts.map((script) => script.getAttribute('src'))).toEqual([
    PLAYFIELD,
    HELPER,
  ])
  expect(scripts.every((script) => script.type === 'module')).toBe(true)
})

it('injects one url once, however often it is asked for', () => {
  injectAssets([PLAYFIELD])
  injectAssets([PLAYFIELD, HELPER])
  injectAssets([PLAYFIELD, HELPER])

  expect(injectedAssets()).toEqual([PLAYFIELD, HELPER])
})

it('reads the document rather than a record of its own', () => {
  injectAssets([PLAYFIELD])
  expect(assetLoaded(PLAYFIELD)).toBe(true)

  document.head.querySelector(`script[${ASSET_ATTRIBUTE}="${PLAYFIELD}"]`)?.remove()

  expect(assetLoaded(PLAYFIELD)).toBe(false)
})

describe('an asset that will not load', () => {
  it('is reported, and is not the app’s crash', () => {
    const reported = vi.spyOn(console, 'error').mockImplementation(() => {})
    injectAssets([PLAYFIELD])

    const script = document.head.querySelector(`script[${ASSET_ATTRIBUTE}]`)
    script?.dispatchEvent(new Event('error'))

    // The element the module would have defined never appears, and the
    // pane draws the card that names the tag (09 §Panel kinds).
    expect(reported).toHaveBeenCalledWith(
      expect.stringContaining('a plugin asset failed to load'),
    )
  })
})
