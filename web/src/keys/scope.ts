/**
 * Who owns the keyboard, and where `a`/`d` are live.
 *
 * The keyboard map is one global map with two rules cut out of it:
 * "shortcuts are suppressed inside inputs", and
 * "requests add `a` allow / `d` deny **when the request panel has
 * focus**". The first is a property of the event's target and belongs to
 * the handler (`./useKeymap.ts`); the other two are properties of what
 * is on screen, and this is where they are registered.
 *
 * **An overlay owns the keyboard while it is up.** A dialog traps focus
 * and has its own keys — cmdk's list, a form's fields, a picker's rows —
 * so a `d` inside one must not reach the delete confirm any more than a
 * `d` typed into the filter input may (D51). Each overlay claims the
 * keyboard for as long as it is open rather than the shell inferring it
 * from `?overlay=`: a plugin panel that opens a dialog of its own
 * (T070) is not a search parameter, and the rule it needs is the same
 * one.
 *
 * **The request panel registers the two keys it adds**, with the element
 * that has to contain the keystroke for them to fire. That is the whole
 * of "when the request panel has focus": three panels can be on screen
 * at once — the pane's cards, the inbox's, and the one docked under the
 * agent stream — and only the one the operator is in answers.
 *
 * Neither registry is React state. Nothing re-renders when a scope
 * changes: they are read inside a `keydown` handler, at the moment the
 * key is pressed, and a store would only add a render pass to a fact the
 * handler is about to read from the DOM anyway.
 */
import { useEffect, useRef, type RefObject } from 'react'

/* -------------------------------------------------------------------- */
/* Overlays                                                              */
/* -------------------------------------------------------------------- */

/** The claims currently held. A claim is its own token; nothing reads it. */
const owners = new Set<object>()

/**
 * Take the keyboard away from the global map until the returned function
 * is called. Calling it twice releases once, which is what a React
 * effect cleanup needs.
 */
export function claimKeyboard(): () => void {
  const token = {}
  owners.add(token)
  return () => {
    owners.delete(token)
  }
}

/** Whether anything other than the app shell owns the keyboard. */
export function keyboardOwned(): boolean {
  return owners.size > 0
}

/**
 * Claim the keyboard while `active`: what an overlay calls with its own
 * `open` prop.
 */
export function useKeyOwner(active: boolean): void {
  useEffect(() => {
    if (!active) return undefined
    return claimKeyboard()
  }, [active])
}

/* -------------------------------------------------------------------- */
/* The request panel                                                     */
/* -------------------------------------------------------------------- */

/**
 * What `a` and `d` do in one request panel.
 *
 * Either may be `null`: a `text` or `form` request has no options at
 * all, and an `options` request that offers no `allow*` kind — a
 * `human_input` choice, whose labels are plain (06 §The model) — has
 * nothing for `a` to pick. A key with nothing to do does nothing, and in
 * particular does not fall through to the global map.
 */
export type AnswerKeys = {
  /** `a`: answer with the allow option, or `null` if none is offered. */
  allow: (() => void) | null
  /** `d`: answer with the deny option, or `null` if none is offered. */
  deny: (() => void) | null
}

/** One registered panel: its root, and what its two keys currently do. */
type AnswerScope = {
  root: () => HTMLElement | null
  keys: () => AnswerKeys
}

const answerScopes = new Set<AnswerScope>()

/** Register a panel's keys until the returned function is called. */
export function registerAnswerKeys(scope: AnswerScope): () => void {
  answerScopes.add(scope)
  return () => {
    answerScopes.delete(scope)
  }
}

/**
 * The keys of the panel containing `target`, or `null` when the
 * keystroke did not come from one.
 *
 * Containment and not a stored "focused panel" flag: focus moves by
 * click, by `tab` and by a dialog closing, and the element the keystroke
 * came from is the one fact that is true at the moment the key is
 * pressed however it got there.
 */
export function answerKeysAt(target: EventTarget | null): AnswerKeys | null {
  if (!(target instanceof Node)) return null

  for (const scope of answerScopes) {
    const root = scope.root()
    if (root !== null && root.contains(target)) return scope.keys()
  }

  return null
}

/**
 * Register `keys` for as long as this component is mounted, against the
 * element `root` points at.
 *
 * The handlers are held in a ref and read when a key is pressed, so a
 * panel whose mutation state changes on every render registers once.
 */
export function useAnswerKeys(
  root: RefObject<HTMLElement | null>,
  keys: AnswerKeys,
): void {
  const held = useRef(keys)

  useEffect(() => {
    held.current = keys
  })

  useEffect(
    () =>
      registerAnswerKeys({
        root: () => root.current,
        keys: () => held.current,
      }),
    [root],
  )
}
