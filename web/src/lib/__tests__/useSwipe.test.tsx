/**
 * `useSwipe`: the recogniser behind the narrow global screen's gesture
 * (`../useSwipe.ts`, `docs/v1/21-design-refresh.md` §Touch operation,
 * D216).
 *
 * jsdom dispatches a `TouchEvent` but performs no layout, so what is
 * driven here is the arithmetic and the refusals: travel, ratio, the
 * edges, a second finger, a cancelled touch, a text field and a
 * horizontal scroller on the way up. Whether a real finger on a real
 * phone reaches the inbox is `web/e2e/mobile.spec.ts`'s.
 */
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { narrowViewport, wideViewport } from './fixtures'
import { EDGE, RATIO, TRAVEL, useSwipe, type SwipeDirection } from '../useSwipe'

/** iPhone-class: what the edges are measured against. */
const WIDTH = 390

/** One element under the hook, with whatever a test puts inside it. */
function Region({
  onSwipe,
  children,
}: {
  onSwipe: ((direction: SwipeDirection) => void) | undefined
  children?: ReactNode
}) {
  const ref = useSwipe(onSwipe)
  return (
    <div ref={ref} data-testid="region">
      {children}
    </div>
  )
}

/** A finger down at `from`, up at `to`, on `target`. */
function drag(
  target: Element,
  from: { x: number; y: number },
  to: { x: number; y: number },
): void {
  fireEvent.touchStart(target, { touches: [{ clientX: from.x, clientY: from.y }] })
  fireEvent.touchEnd(target, { changedTouches: [{ clientX: to.x, clientY: to.y }] })
}

afterEach(wideViewport)

describe('useSwipe', () => {
  it('reads a swipe right, and a swipe left', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(<Region onSwipe={onSwipe} />)
    const region = screen.getByTestId('region')

    drag(region, { x: 100, y: 300 }, { x: 220, y: 300 })
    expect(onSwipe).toHaveBeenCalledExactlyOnceWith('right')

    onSwipe.mockClear()
    drag(region, { x: 220, y: 300 }, { x: 100, y: 300 })
    expect(onSwipe).toHaveBeenCalledExactlyOnceWith('left')
  })

  it('needs the travel: a short drag is nothing', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(<Region onSwipe={onSwipe} />)

    const region = screen.getByTestId('region')
    drag(region, { x: 100, y: 300 }, { x: 100 + TRAVEL - 20, y: 300 })
    expect(onSwipe).not.toHaveBeenCalled()
  })

  it('needs the ratio: a diagonal that went as far down as across is a scroll', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(<Region onSwipe={onSwipe} />)
    const region = screen.getByTestId('region')

    // 80 px across and 60 px down: enough travel, less than 2:1.
    drag(region, { x: 100, y: 300 }, { x: 180, y: 360 })
    expect(onSwipe).not.toHaveBeenCalled()

    // ...and exactly at the ratio it counts.
    drag(region, { x: 100, y: 300 }, { x: 100 + RATIO * 40, y: 340 })
    expect(onSwipe).toHaveBeenCalledExactlyOnceWith('right')
  })

  it('ignores a start at either edge: that is the browser’s back gesture', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(<Region onSwipe={onSwipe} />)
    const region = screen.getByTestId('region')

    drag(region, { x: 10, y: 300 }, { x: 200, y: 300 })
    drag(region, { x: WIDTH - 10, y: 300 }, { x: WIDTH - 200, y: 300 })
    expect(onSwipe).not.toHaveBeenCalled()

    // Just inside the edge is the region's.
    drag(region, { x: EDGE, y: 300 }, { x: EDGE + 120, y: 300 })
    expect(onSwipe).toHaveBeenCalledExactlyOnceWith('right')
  })

  it('ignores a start inside a text field: a drag there selects text', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(
      <Region onSwipe={onSwipe}>
        <input aria-label="note" />
        <textarea aria-label="longer note" />
      </Region>,
    )

    const input = screen.getByRole('textbox', { name: 'note' })
    const textarea = screen.getByRole('textbox', { name: 'longer note' })
    drag(input, { x: 100, y: 300 }, { x: 250, y: 300 })
    drag(textarea, { x: 100, y: 300 }, { x: 250, y: 300 })
    expect(onSwipe).not.toHaveBeenCalled()
  })

  it('ignores a start inside something that scrolls horizontally, not a fitted one', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(
      <Region onSwipe={onSwipe}>
        <div data-testid="wrapper" style={{ overflowX: 'auto' }}>
          <table>
            <tbody>
              <tr>
                <td data-testid="cell">wide</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Region>,
    )
    const wrapper = screen.getByTestId('wrapper')
    const cell = screen.getByTestId('cell')
    // jsdom performs no layout, so the wrapper says what it would measure:
    // a shadcn table wider than its box (`overflow-x-auto`).
    Object.defineProperty(wrapper, 'scrollWidth', { configurable: true, value: 800 })
    Object.defineProperty(wrapper, 'clientWidth', { configurable: true, value: 300 })

    // The finger is on a cell; the scroller is on the way up to the region.
    drag(cell, { x: 100, y: 300 }, { x: 250, y: 300 })
    expect(onSwipe).not.toHaveBeenCalled()

    // The same wrapper with nothing to scroll is not scrolling anything.
    Object.defineProperty(wrapper, 'scrollWidth', { configurable: true, value: 300 })
    drag(cell, { x: 100, y: 300 }, { x: 250, y: 300 })
    expect(onSwipe).toHaveBeenCalledExactlyOnceWith('right')
  })

  it('ignores two fingers: a pinch is the browser’s', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(<Region onSwipe={onSwipe} />)
    const region = screen.getByTestId('region')

    fireEvent.touchStart(region, {
      touches: [
        { clientX: 100, clientY: 300 },
        { clientX: 140, clientY: 300 },
      ],
    })
    fireEvent.touchEnd(region, { changedTouches: [{ clientX: 250, clientY: 300 }] })
    expect(onSwipe).not.toHaveBeenCalled()
  })

  it('forgets a cancelled touch', () => {
    narrowViewport(WIDTH)
    const onSwipe = vi.fn()
    render(<Region onSwipe={onSwipe} />)
    const region = screen.getByTestId('region')

    fireEvent.touchStart(region, { touches: [{ clientX: 100, clientY: 300 }] })
    fireEvent.touchCancel(region)
    fireEvent.touchEnd(region, { changedTouches: [{ clientX: 250, clientY: 300 }] })
    expect(onSwipe).not.toHaveBeenCalled()

    // ...and an end with no start is nothing either.
    fireEvent.touchEnd(region, { changedTouches: [{ clientX: 250, clientY: 300 }] })
    expect(onSwipe).not.toHaveBeenCalled()
  })

  it('listens to nothing without a handler, passively with one', () => {
    // Spied on the element and not the prototype: React's root registers
    // touch listeners of its own on the container, and those are not
    // what this is about.
    narrowViewport(WIDTH)
    const { rerender } = render(<Region onSwipe={undefined} />)
    const region = screen.getByTestId('region')
    const added = vi.spyOn(region, 'addEventListener')

    rerender(<Region onSwipe={undefined} />)
    expect(added).not.toHaveBeenCalled()

    const onSwipe = vi.fn()
    rerender(<Region onSwipe={onSwipe} />)
    expect(added.mock.calls.map(([type]) => type).sort()).toEqual([
      'touchcancel',
      'touchend',
      'touchstart',
    ])
    // Passive: the region scrolls, and a listener that could cancel a
    // touch would put every scroll on the slow path.
    for (const [, , options] of added.mock.calls) {
      expect(options).toEqual({ passive: true })
    }
    added.mockRestore()
  })

  it('keeps the start across a re-render mid-gesture', () => {
    // The shell passes an inline arrow: a run-list refresh between the
    // finger going down and coming up must not drop the swipe.
    narrowViewport(WIDTH)
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = render(<Region onSwipe={first} />)
    const region = screen.getByTestId('region')

    fireEvent.touchStart(region, { touches: [{ clientX: 100, clientY: 300 }] })
    rerender(<Region onSwipe={second} />)
    fireEvent.touchEnd(region, { changedTouches: [{ clientX: 250, clientY: 300 }] })

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledExactlyOnceWith('right')
  })
})
