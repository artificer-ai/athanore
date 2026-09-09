/**
 * `keys/scope.ts`: who owns the keyboard, and where `a`/`d` are live.
 *
 * Both registries are plain module state read inside a `keydown`
 * handler, so they are tested as what they are — two small collections
 * with an add and a remove — and the hooks that wrap them are exercised
 * through the components that call them (`./useKeymap.test.tsx`,
 * `components/__tests__/RequestPanel.test.tsx`).
 */
import { afterEach, describe, expect, it } from 'vitest'

import {
  answerKeysAt,
  claimKeyboard,
  keyboardOwned,
  registerAnswerKeys,
  type AnswerKeys,
} from '../scope'

const release: Array<() => void> = []

/** Claim the keyboard, and remember how to give it back. */
function claim(): () => void {
  const back = claimKeyboard()
  release.push(back)
  return back
}

afterEach(() => {
  // Module state outlives a test, so nothing may leak into the next one.
  for (const back of release.splice(0)) back()
  document.body.innerHTML = ''
})

describe('the keyboard owners', () => {
  it('is the app’s until something claims it', () => {
    expect(keyboardOwned()).toBe(false)

    const back = claim()
    expect(keyboardOwned()).toBe(true)

    back()
    expect(keyboardOwned()).toBe(false)
  })

  it('stays claimed while any one claim is outstanding', () => {
    // Two overlays can be mounted at once mid-transition: the one
    // closing has not unmounted when the one opening has mounted.
    const first = claim()
    const second = claim()

    first()
    expect(keyboardOwned()).toBe(true)

    second()
    expect(keyboardOwned()).toBe(false)
  })

  it('releases once however often the release is called', () => {
    const back = claim()
    back()
    back()

    claim()
    expect(keyboardOwned()).toBe(true)
  })
})

describe('the request panel’s two keys', () => {
  /** A panel around a button, registered with `keys`. */
  function panel(keys: AnswerKeys) {
    const root = document.createElement('div')
    const button = document.createElement('button')
    root.append(button)
    document.body.append(root)
    release.push(registerAnswerKeys({ root: () => root, keys: () => keys }))
    return { root, button }
  }

  const keys: AnswerKeys = { allow: () => {}, deny: () => {} }

  it('answers for a keystroke from inside the panel', () => {
    const { root, button } = panel(keys)

    expect(answerKeysAt(root)).toBe(keys)
    // From a control inside it, which is where focus actually is.
    expect(answerKeysAt(button)).toBe(keys)
  })

  it('answers for nothing outside it', () => {
    panel(keys)
    const elsewhere = document.createElement('input')
    document.body.append(elsewhere)

    expect(answerKeysAt(elsewhere)).toBeNull()
    expect(answerKeysAt(document.body)).toBeNull()
    expect(answerKeysAt(null)).toBeNull()
    expect(answerKeysAt(window)).toBeNull()
  })

  it('picks the panel the keystroke came from, of several on screen', () => {
    // The pane's cards, the inbox's and the docked one are three
    // panels; only the one the operator is in answers.
    const other: AnswerKeys = { allow: null, deny: null }
    panel(keys)
    const second = panel(other)

    expect(answerKeysAt(second.button)).toBe(other)
  })

  it('forgets a panel that has unregistered', () => {
    const { button } = panel(keys)
    const back = release.pop()
    back?.()

    expect(answerKeysAt(button)).toBeNull()
  })
})
