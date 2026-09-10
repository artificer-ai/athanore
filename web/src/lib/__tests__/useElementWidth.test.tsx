/**
 * `lib/useElementWidth.ts`: the measurement the graph pane chooses its
 * layout on.
 *
 * jsdom performs no layout, so the `ResizeObserver` of `src/test-setup.ts`
 * never reports anything — which is precisely the "not measured yet"
 * state this hook has to have an answer for, and precisely what every
 * other suite in this repository is relying on when it renders a pane and
 * gets the viewport's layout. Both halves are asserted here: the null
 * that jsdom produces, and the widths a browser's observer produces,
 * through a stand-in installed for this file only.
 */
import { render, screen } from '@testing-library/react'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import { useElementWidth } from '../useElementWidth'

/** The observers the stand-in has handed out, newest last. */
let observers: FakeResizeObserver[] = []

class FakeResizeObserver {
  readonly callback: ResizeObserverCallback
  readonly observed: Element[] = []
  disconnected = false

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    observers.push(this)
  }

  observe(target: Element): void {
    this.observed.push(target)
  }

  unobserve(): void {}

  disconnect(): void {
    this.disconnected = true
  }

  /** What a browser does when the observed box changes width. */
  report(...widths: number[]): void {
    act(() => {
      this.callback(
        widths.map((width) => ({ contentRect: { width } }) as ResizeObserverEntry),
        this as unknown as ResizeObserver,
      )
    })
  }
}

function Probe() {
  const [measure, width] = useElementWidth()
  return (
    <div ref={measure} data-testid="box">
      {width === null ? 'unmeasured' : String(width)}
    </div>
  )
}

function reading(): string {
  return screen.getByTestId('box').textContent ?? ''
}

describe('useElementWidth', () => {
  const real = globalThis.ResizeObserver

  beforeEach(() => {
    observers = []
    globalThis.ResizeObserver = FakeResizeObserver as unknown as typeof ResizeObserver
  })

  afterEach(() => {
    globalThis.ResizeObserver = real
  })

  it('reports null until the observer has answered', () => {
    render(<Probe />)

    expect(reading()).toBe('unmeasured')
    expect(observers).toHaveLength(1)
    expect(observers[0]!.observed).toEqual([screen.getByTestId('box')])
  })

  it('reports the observed content width', () => {
    render(<Probe />)
    observers[0]!.report(742.5)

    expect(reading()).toBe('742.5')
  })

  it('takes the last entry of a coalesced callback', () => {
    render(<Probe />)
    observers[0]!.report(300, 900)

    expect(reading()).toBe('900')
  })

  it('ignores a zero, so a hidden pane keeps its last real width', () => {
    render(<Probe />)
    observers[0]!.report(742)
    observers[0]!.report(0)

    expect(reading()).toBe('742')
  })

  it('disconnects when the element goes away', () => {
    const view = render(<Probe />)
    view.unmount()

    expect(observers[0]!.disconnected).toBe(true)
  })
})

describe('useElementWidth without a laying-out browser', () => {
  it('stays null, which is what every jsdom suite renders against', () => {
    render(<Probe />)

    expect(reading()).toBe('unmeasured')
  })
})
