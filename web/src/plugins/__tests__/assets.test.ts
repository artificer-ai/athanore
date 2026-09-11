/**
 * Injecting a plugin's JavaScript (`../assets.ts`).
 *
 * "The SPA injects them once as `<script type="module">`" is two claims,
 * and the second is the one with teeth: a module cannot be un-executed,
 * so a second `<script>` for one URL would run the plugin's
 * `customElements.define` a second time and throw.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  ASSET_ATTRIBUTE,
  assetLoaded,
  assetPath,
  injectAssets,
  injectedAssets,
  staleAssets,
} from '../assets'

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

describe('a path the document already ran at another version', () => {
  const V1 = `${PLAYFIELD}?v=aaaaaaaaaaaa`
  const V2 = `${PLAYFIELD}?v=bbbbbbbbbbbb`

  it('splits a manifest url into its path and nothing else', () => {
    expect(assetPath(V1)).toBe(PLAYFIELD)
    expect(assetPath(PLAYFIELD)).toBe(PLAYFIELD)
    expect(assetPath('/plugins/gamedev/static/a.js?v=1&x=?')).toBe(
      '/plugins/gamedev/static/a.js',
    )
  })

  it('is not stale on a first injection', () => {
    expect(staleAssets([V1, HELPER])).toEqual([])
  })

  it('is not stale when the manifest lists what is loaded', () => {
    injectAssets([V1, HELPER])

    expect(staleAssets([V1, HELPER])).toEqual([])
  })

  it('is not stale when a workflow is removed and lists nothing', () => {
    injectAssets([V1])

    expect(staleAssets([])).toEqual([])
  })

  it('names the url whose path is loaded under a different ?v=', () => {
    injectAssets([V1, HELPER])

    // The reload changed one file: the helper's bytes, and so its
    // version, are what they were.
    expect(staleAssets([V2, HELPER])).toEqual([V2])
  })

  it('never injects the second version of one path', () => {
    injectAssets([V1])
    injectAssets([V2])

    // One script, and it is the one that ran: a second would run the
    // plugin's `customElements.define` again and throw (D225).
    expect(injectedAssets()).toEqual([V1])
  })

  it('still injects a path that is new beside one that is stale', () => {
    injectAssets([V1])
    injectAssets([V2, HELPER])

    expect(injectedAssets()).toEqual([V1, HELPER])
  })
})
