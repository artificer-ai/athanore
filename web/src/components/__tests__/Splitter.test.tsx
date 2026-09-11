import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  DEFAULT_LIST_WIDTH,
  MIN_DETAIL_WIDTH,
  MIN_LIST_WIDTH,
  usePrefs,
} from '../../store/prefs'
import { Splitter } from '../Splitter'

/**
 * jsdom performs no layout, and every pixel the splitter works in comes
 * from the DOM: `react-resizable-panels` reads the panels' `offsetWidth`
 * for the group's size and their `offsetLeft` for their order. This is
 * the window the tests below resize in — 1000 px wide, the 5 px handle
 * between a 540 px list and a 460 px detail pane, which is the mock's
 * own arrangement.
 */
const GROUP_WIDTH = 1000

const GEOMETRY: Record<string, { offsetLeft: number; offsetWidth: number }> = {
  'list-panel': { offsetLeft: 0, offsetWidth: 540 },
  'list-splitter': { offsetLeft: 540, offsetWidth: 5 },
  'detail-panel': { offsetLeft: 545, offsetWidth: 460 },
}

const OFFSET_PROPERTIES = ['offsetLeft', 'offsetWidth'] as const

const originals = OFFSET_PROPERTIES.map((name) => ({
  name,
  descriptor: Object.getOwnPropertyDescriptor(HTMLElement.prototype, name),
}))

beforeEach(() => {
  for (const name of OFFSET_PROPERTIES) {
    Object.defineProperty(HTMLElement.prototype, name, {
      configurable: true,
      get(this: HTMLElement) {
        return GEOMETRY[this.id]?.[name] ?? 0
      },
    })
  }

  usePrefs.setState({ listWidth: DEFAULT_LIST_WIDTH, listCollapsed: false })
})

afterEach(() => {
  for (const { name, descriptor } of originals) {
    if (descriptor) Object.defineProperty(HTMLElement.prototype, name, descriptor)
    else delete (HTMLElement.prototype as unknown as Record<string, unknown>)[name]
  }
})

function splitter() {
  return render(<Splitter count={34} list={<p>the runs</p>} detail={<p>the pane</p>} />)
}

/** What the handle's ARIA percentage is in this window's pixels. */
function pixels(attribute: string): number {
  const value = screen.getByRole('separator').getAttribute(attribute)
  expect(value).not.toBeNull()
  return (Number(value) / 100) * GROUP_WIDTH
}

describe('Splitter', () => {
  it('puts the list and the detail pane either side of the handle', () => {
    splitter()

    expect(screen.getByTestId('list-panel')).toHaveTextContent('the runs')
    expect(screen.getByTestId('detail-panel')).toHaveTextContent('the pane')
    expect(screen.getByRole('separator', { name: 'resize run list' })).toHaveClass(
      'w-[5px]',
    )
  })

  it('lays the list out at the width prefs remembers', () => {
    usePrefs.setState({ listWidth: 400 })
    splitter()

    // The group divides its width by the panels' `flex-grow`, so 400 of
    // this window's 1000 pixels is a grow of 40.
    expect(screen.getByTestId('list-panel').style.flexGrow).toBe('40')
  })

  it('clamps the drag at the narrow end: the list keeps 260 px', () => {
    splitter()

    expect(pixels('aria-valuemin')).toBeCloseTo(MIN_LIST_WIDTH, 0)
  })

  it('clamps the drag at the wide end: the detail pane keeps 340 px', () => {
    splitter()

    expect(pixels('aria-valuemax')).toBeCloseTo(GROUP_WIDTH - MIN_DETAIL_WIDTH, 0)
  })

  it('keeps the width the operator settled on', async () => {
    splitter()
    const handle = screen.getByRole('separator')
    handle.focus()

    // A resize key is a user interaction like the pointer: the group
    // moves the boundary and reports the layout it moved to.
    await userEvent.keyboard('{ArrowLeft}')

    const stored = usePrefs.getState().listWidth
    expect(stored).toBeLessThan(GROUP_WIDTH - MIN_DETAIL_WIDTH)
    expect(stored).toBeGreaterThanOrEqual(MIN_LIST_WIDTH)
    expect(stored).not.toBe(DEFAULT_LIST_WIDTH)
  })

  it('leaves the stored width alone when the operator did not move it', () => {
    // The initial mount lays the group out and reports it, as a window
    // resize and a remount do. None of the three is the operator, and a
    // narrow window must not quietly rewrite a width chosen on a wide
    // one.
    usePrefs.setState({ listWidth: 400 })
    const { rerender } = splitter()
    rerender(<Splitter count={35} list={<p>the runs</p>} detail={<p>the pane</p>} />)

    expect(usePrefs.getState().listWidth).toBe(400)
  })

  it('collapses to the rail, which reports the count sideways', () => {
    usePrefs.setState({ listCollapsed: true })
    splitter()

    expect(screen.queryByText('the runs')).toBeNull()
    expect(screen.queryByRole('separator')).toBeNull()

    const rail = screen.getByRole('button', { name: 'show run list' })
    expect(rail).toHaveClass('w-[30px]')
    expect(screen.getByTestId('runs-rail')).toHaveTextContent('RUNS 34')
    // The detail pane is the whole of the rest of the window.
    expect(screen.getByText('the pane')).toBeInTheDocument()
  })

  it('expands the list again when the rail is clicked', async () => {
    usePrefs.setState({ listCollapsed: true })
    splitter()

    await userEvent.click(screen.getByRole('button', { name: 'show run list' }))

    expect(usePrefs.getState().listCollapsed).toBe(false)
    expect(screen.getByText('the runs')).toBeInTheDocument()
    expect(screen.getByRole('separator')).toBeInTheDocument()
  })

  describe('stacked', () => {
    /** A finger down at `from`, up at `to`, on the stacked middle. */
    function drag(from: number, to: number) {
      const main = screen.getByRole('main')
      fireEvent.touchStart(main, { touches: [{ clientX: from, clientY: 400 }] })
      fireEvent.touchEnd(main, { changedTouches: [{ clientX: to, clientY: 400 }] })
    }

    it('draws the detail slot as the global screen, and says so', () => {
      // The third stacked state (D216): the same `detail` slot — the
      // shell hands it a `Detail` over the global cycle — marked for
      // the test that wants to know which screen this is.
      render(
        <Splitter
          count={34}
          list={<p>the runs</p>}
          detail={<p>the pane</p>}
          stacked="global"
        />,
      )

      expect(screen.getByRole('main')).toHaveAttribute('data-stacked', 'global')
      expect(screen.getByText('the pane')).toBeInTheDocument()
      expect(screen.queryByText('the runs')).toBeNull()
      expect(screen.queryByRole('separator')).toBeNull()
    })

    it('reads a swipe on the stacked middle', () => {
      const onSwipe = vi.fn()
      render(
        <Splitter
          count={34}
          list={<p>the runs</p>}
          detail={<p>the pane</p>}
          stacked="list"
          onSwipe={onSwipe}
        />,
      )

      drag(100, 260)
      expect(onSwipe).toHaveBeenCalledExactlyOnceWith('right')
      onSwipe.mockClear()
      drag(260, 100)
      expect(onSwipe).toHaveBeenCalledExactlyOnceWith('left')
    })

    it('listens to nothing in the split layout', () => {
      // The gesture is a property of the stacked middle; the desktop
      // split has none, however the shell is called.
      const onSwipe = vi.fn()
      render(
        <Splitter
          count={34}
          list={<p>the runs</p>}
          detail={<p>the pane</p>}
          onSwipe={onSwipe}
        />,
      )

      drag(100, 260)
      expect(onSwipe).not.toHaveBeenCalled()
    })
  })
})
