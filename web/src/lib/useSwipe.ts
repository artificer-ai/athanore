/**
 * A horizontal swipe on one element, read by touch
 * (`docs/v1/21-design-refresh.md` §Touch operation, D216).
 *
 * The three narrow screens fan around the list — global | list |
 * detail — and a swipe on the middle region is one screen along that
 * row, the way the finger moved (`components/Splitter.tsx`, D218).
 * This is the recogniser and nothing else: it says which way a finger
 * went and leaves what that means to the caller.
 *
 * The listeners are **native** and **passive**, and both words matter.
 * Native rather than React's `onTouchStart`, because React propagates
 * synthetic events through *portals*: every overlay portals out of the
 * middle region but is still its React descendant, so a finger on a
 * sheet would reach a React handler on the region under it and move the
 * screen the sheet is covering. A native listener on the element hears
 * only what is inside the element. Passive, because the region scrolls
 * vertically and a touch listener that could `preventDefault` puts every
 * scroll in it on the slow path; nothing here needs to cancel anything,
 * and nothing here touches `touch-action`.
 *
 * What is **not** a swipe, checked at `touchstart` so a drag that is
 * something else is never scored:
 *
 * - a second finger — a pinch is the browser's;
 * - a start within {@link EDGE} of either side of the viewport — the
 *   edges are iOS Safari's and Android Chrome's own back/forward
 *   gesture, and an edge swipe would fire both;
 * - a start inside a text field — a horizontal drag in one selects text;
 * - a start inside an element that **scrolls horizontally** — the shadcn
 *   table wrapper is `overflow-x-auto`, and a finger dragging a wide
 *   table sideways is scrolling it, not leaving the screen.
 *
 * The last two are read off `event.composedPath()` rather than
 * `closest()`, for D210's reason: a plugin's `custom` pane is a shadow
 * root and the touch is retargeted to its host, so the path is the only
 * thing that still sees the field or the scroller inside it. The
 * text-field rule deliberately overlaps `keys/useKeymap.ts`'s
 * `isTyping`; `lib/` sits under `keys/` and does not import from it.
 *
 * Recognition is distance and ratio, with no time cap and no velocity:
 * {@link TRAVEL} px of horizontal movement, at least {@link RATIO} times
 * the vertical. The ratio is what separates a swipe from a vertical
 * scroll that wandered, and the scroller check above is what separates
 * it from a horizontal one.
 *
 * The shape follows `./useElementWidth.ts`: the node is state, not a
 * ref, so an element that mounts after the component does is still
 * listened to, and the hook hands back the callback ref to put on it.
 * The handler itself is kept in a ref and the listeners are keyed on
 * the node and on whether there *is* a handler, not on its identity: the
 * shell passes an inline arrow, and re-attaching between `touchstart`
 * and `touchend` — which a run-list refresh mid-gesture would do —
 * would lose the start point and drop the swipe.
 */
import { useEffect, useRef, useState } from 'react'

export type SwipeDirection = 'left' | 'right'

/** Px from either side of the viewport that are the browser's gesture. */
export const EDGE = 24

/** Px of horizontal travel a swipe needs. */
export const TRAVEL = 60

/** How many times the vertical movement the horizontal must be. */
export const RATIO = 2

/** Whether a horizontal drag starting on `node` would select text. */
function isTextField(node: EventTarget): boolean {
  if (!(node instanceof Element)) return false
  if (node instanceof HTMLElement && node.isContentEditable) return true
  return (
    node instanceof HTMLInputElement ||
    node instanceof HTMLTextAreaElement ||
    node instanceof HTMLSelectElement
  )
}

/** Whether a horizontal drag starting on `node` would scroll it. */
function scrollsHorizontally(node: EventTarget): boolean {
  if (!(node instanceof Element)) return false
  if (node.scrollWidth <= node.clientWidth) return false
  const overflow = getComputedStyle(node).overflowX
  return overflow === 'auto' || overflow === 'scroll'
}

/**
 * Whether a touch starting here is something other than a swipe: a text
 * field or a horizontal scroller anywhere between the finger and the
 * listened element, inclusive.
 */
function claimedByDescendant(event: TouchEvent, element: HTMLElement): boolean {
  for (const node of event.composedPath()) {
    if (isTextField(node) || scrollsHorizontally(node)) return true
    if (node === element) break
  }
  return false
}

/**
 * Read a horizontal swipe on one element, by touch.
 *
 * Returns a callback ref for the element the gesture is read on;
 * `onSwipe` fires once per recognised swipe with the direction the
 * finger moved. `undefined` reads nothing and attaches no listener.
 */
export function useSwipe(
  onSwipe: ((direction: SwipeDirection) => void) | undefined,
): (node: HTMLElement | null) => void {
  const [node, setNode] = useState<HTMLElement | null>(null)
  const handler = useRef(onSwipe)
  const listening = onSwipe !== undefined

  useEffect(() => {
    handler.current = onSwipe
  })

  useEffect(() => {
    if (node === null || !listening) return
    const element = node
    let start: { x: number; y: number } | null = null

    const onStart = (event: TouchEvent) => {
      start = null
      if (event.touches.length !== 1) return
      const touch = event.touches[0]
      if (touch === undefined) return
      if (touch.clientX < EDGE || touch.clientX > window.innerWidth - EDGE) return
      if (claimedByDescendant(event, element)) return
      start = { x: touch.clientX, y: touch.clientY }
    }

    const onEnd = (event: TouchEvent) => {
      const from = start
      start = null
      if (from === null) return
      const touch = event.changedTouches[0]
      if (touch === undefined) return
      const dx = touch.clientX - from.x
      const dy = touch.clientY - from.y
      if (Math.abs(dx) < TRAVEL || Math.abs(dx) < RATIO * Math.abs(dy)) return
      handler.current?.(dx > 0 ? 'right' : 'left')
    }

    const onCancel = () => {
      start = null
    }

    const options: AddEventListenerOptions = { passive: true }
    element.addEventListener('touchstart', onStart, options)
    element.addEventListener('touchend', onEnd, options)
    element.addEventListener('touchcancel', onCancel, options)
    return () => {
      element.removeEventListener('touchstart', onStart, options)
      element.removeEventListener('touchend', onEnd, options)
      element.removeEventListener('touchcancel', onCancel, options)
    }
  }, [node, listening])

  return setNode
}
