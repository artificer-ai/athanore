/**
 * `useKeymap`: `docs/v1/10-frontend.md` §Keyboard, and the scoping that
 * is the reason 10 moved delete off `d` and onto `D` (D51).
 *
 * The map is asserted against the catalogue it dispatches on rather than
 * against a second list written here: every palette row that carries a
 * keycap is pressed, and the row that ran is the row that cap names. A
 * binding somebody forgets to implement therefore fails here, and a test
 * that walked a table of its own would only agree with itself.
 *
 * The scoping tests are the ones the task names, and they are all one
 * question asked from four places: what happened when the key was
 * pressed *there*.
 */
import { render, screen, fireEvent } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { useRef } from 'react'

import { PALETTE_COMMANDS, KEYLESS } from '../../overlays/actions'
import { claimKeyboard, useAnswerKeys } from '../scope'
import { useKeymap, type KeymapAction, type KeymapHandlers } from '../useKeymap'

/** The spies every test asserts on. */
function handlers() {
  return {
    select: vi.fn(),
    cyclePane: vi.fn(),
    jumpPane: vi.fn(),
    toggleRunFocus: vi.fn(),
    moveRun: vi.fn(),
    openPalette: vi.fn(),
    close: vi.fn(),
  }
}

type Spies = ReturnType<typeof handlers>

/** The catalogue, with a spy behind each row. */
function catalogue(disabled = false): { actions: KeymapAction[]; ran: string[] } {
  const ran: string[] = []
  const actions = PALETTE_COMMANDS.map((command) => ({
    key: command.key,
    disabled,
    run: () => {
      if (disabled) return
      ran.push(command.id)
    },
  }))
  return { actions, ran }
}

/** The panel `a` and `d` belong to, registered as the real one is. */
function Panel({ allow, deny }: { allow: () => void; deny: () => void }) {
  const root = useRef<HTMLDivElement | null>(null)
  useAnswerKeys(root, { allow, deny })

  return (
    <div ref={root} data-testid="request-panel">
      <button type="button">Allow once</button>
    </div>
  )
}

/**
 * The four places a key can be pressed: an input, the run list, the
 * request panel, and the page itself.
 */
function Harness({
  keymap,
  allow,
  deny,
}: {
  keymap: KeymapHandlers
  allow: () => void
  deny: () => void
}) {
  useKeymap(keymap)

  return (
    <>
      <input aria-label="filter runs" />
      <textarea aria-label="a note" />
      <div aria-label="a document" contentEditable suppressContentEditableWarning />
      <section aria-label="runs" data-region="list">
        <button type="button">a run row</button>
      </section>
      <section aria-label="detail" data-region="detail">
        <Panel allow={allow} deny={deny} />
      </section>
    </>
  )
}

let spies: Spies
let allow: Mock<() => void>
let deny: Mock<() => void>
let released: Array<() => void>

/** Mount the harness over `actions`, with or without a run held. */
function mount(actions: readonly KeymapAction[], runFocused = false) {
  return render(
    <Harness keymap={{ ...spies, actions, runFocused }} allow={allow} deny={deny} />,
  )
}

/** Nothing in the map ran. */
function nothingHappened(ran: string[]) {
  expect(ran).toEqual([])
  for (const spy of Object.values(spies)) expect(spy).not.toHaveBeenCalled()
  expect(allow).not.toHaveBeenCalled()
  expect(deny).not.toHaveBeenCalled()
}

const list = () => screen.getByRole('region', { name: 'runs' })
const panel = () => screen.getByTestId('request-panel')
const filter = () => screen.getByRole('textbox', { name: 'filter runs' })

beforeEach(() => {
  spies = handlers()
  allow = vi.fn<() => void>()
  deny = vi.fn<() => void>()
  released = []
})

afterEach(() => {
  for (const back of released.splice(0)) back()
})

/* -------------------------------------------------------------------- */
/* The table                                                             */
/* -------------------------------------------------------------------- */

describe('the map', () => {
  it('runs the catalogue row each keycap names', () => {
    for (const command of PALETTE_COMMANDS) {
      if (command.key === KEYLESS) continue

      const { actions, ran } = catalogue()
      const view = mount(actions)

      const chord = command.key.startsWith('^')
      fireEvent.keyDown(document.body, {
        key: chord ? command.key.slice(1) : command.key,
        ctrlKey: chord,
      })

      expect(ran, `\`${command.key}\` runs ${command.name}`).toEqual([command.id])
      view.unmount()
    }
  })

  it('leaves the six keyless rows without a key', () => {
    // `reorder` is an operator op 10 §Keyboard has no binding for, and
    // that section is exhaustive: the palette prints `—` for it and the
    // map has nothing to dispatch (D175). The four font-size steps are
    // the same: they are the palette's half of the header's chooser and
    // 10 §Keyboard binds no key to them either (D196).
    const keyless = PALETTE_COMMANDS.filter((command) => command.key === KEYLESS)
    expect(keyless.map((command) => command.id)).toEqual([
      'move-run-up',
      'move-run-down',
      'font-size-small',
      'font-size-default',
      'font-size-large',
      'font-size-xlarge',
    ])
  })

  it('selects with `↑`/`↓` and `j`/`k`, clamped by the shell', () => {
    const { actions } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: 'ArrowDown' })
    fireEvent.keyDown(document.body, { key: 'j' })
    fireEvent.keyDown(document.body, { key: 'ArrowUp' })
    fireEvent.keyDown(document.body, { key: 'k' })

    expect(spies.select.mock.calls).toEqual([[1], [1], [-1], [-1]])
  })

  it('cycles the panes with `←`/`→`', () => {
    const { actions } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: 'ArrowRight' })
    fireEvent.keyDown(document.body, { key: 'ArrowLeft' })

    expect(spies.cyclePane.mock.calls).toEqual([[1], [-1]])
  })

  it('jumps to a pane with `1`–`9`, and nowhere with `0`', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: '1' })
    fireEvent.keyDown(document.body, { key: '9' })
    expect(spies.jumpPane.mock.calls).toEqual([[0], [8]])

    spies.jumpPane.mockClear()
    fireEvent.keyDown(document.body, { key: '0' })
    expect(spies.jumpPane).not.toHaveBeenCalled()
    expect(ran).toEqual([])
  })

  it('opens the palette on `^p` and refuses the browser its own `^r`', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    const palette = fireEvent.keyDown(document.body, { key: 'p', ctrlKey: true })
    expect(spies.openPalette).toHaveBeenCalledOnce()
    // The chord is the app's: the browser must not also print the page.
    expect(palette).toBe(false)

    const refresh = fireEvent.keyDown(document.body, { key: 'r', ctrlKey: true })
    expect(ran).toEqual(['refresh'])
    expect(refresh).toBe(false)
  })

  it('leaves an `alt` chord alone', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: 'n', altKey: true })
    nothingHappened(ran)
  })

  it('does not run a row this state has disabled', () => {
    // "retry task" with no run selected is a command that exists and is
    // not available (`overlays/actions.ts`).
    const { actions, ran } = catalogue(true)
    mount(actions)

    fireEvent.keyDown(document.body, { key: 't' })
    expect(ran).toEqual([])
  })

  it('leaves a key nothing in the map claims', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    const handled = fireEvent.keyDown(document.body, { key: 'z' })
    expect(handled).toBe(true)
    nothingHappened(ran)
  })

  it('leaves a chord nothing in the map claims', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    // `^z` is the browser's undo and nothing of this app's: taken and
    // dropped, it would be a keystroke the operator lost.
    const handled = fireEvent.keyDown(document.body, { key: 'z', ctrlKey: true })
    expect(handled).toBe(true)
    nothingHappened(ran)
  })

  it('leaves a chord whose key is not one character', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    // `^↓` is not a keycap this app writes down, and `^ArrowDown` is not
    // a spelling of one: `capOf` answers `null` rather than inventing it.
    const handled = fireEvent.keyDown(document.body, { key: 'ArrowDown', ctrlKey: true })
    expect(handled).toBe(true)
    nothingHappened(ran)
  })

  it('takes the same chord from the meta key, for a mac', () => {
    const { actions } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: 'p', metaKey: true })

    expect(spies.openPalette).toHaveBeenCalledOnce()
  })

  it('leaves a key something nearer has already dealt with', () => {
    // A Radix dialog consuming `esc`, a composer consuming `⏎`.
    const { actions, ran } = catalogue()
    mount(actions)

    const event = new KeyboardEvent('keydown', {
      key: 'Escape',
      bubbles: true,
      cancelable: true,
    })
    event.preventDefault()
    window.dispatchEvent(event)

    nothingHappened(ran)
  })

  it('stops listening once the component is unmounted', () => {
    const { actions, ran } = catalogue()
    const { unmount } = mount(actions)

    unmount()
    fireEvent.keyDown(document.body, { key: 'n' })

    expect(ran).toEqual([])
  })
})

/* -------------------------------------------------------------------- */
/* `⏎` focus run                                                         */
/* -------------------------------------------------------------------- */

describe('`⏎`', () => {
  it('picks the highlighted run up, from the run list', () => {
    const { actions } = catalogue()
    mount(actions)

    fireEvent.keyDown(list(), { key: 'Enter' })
    expect(spies.toggleRunFocus).toHaveBeenCalledOnce()
  })

  it('does the same from a run row, and does only that', () => {
    // The row is a `<button>`, so the key is cancelled: `↑`/`↓` and
    // `j`/`k` select a run — the list's own footer strip says so —
    // and Enter is the other half of that pair, not a second way to
    // press the row.
    const { actions } = catalogue()
    mount(actions)

    const cancelled = fireEvent.keyDown(
      screen.getByRole('button', { name: 'a run row' }),
      { key: 'Enter' },
    )

    expect(spies.toggleRunFocus).toHaveBeenCalledOnce()
    expect(cancelled).toBe(false)
  })

  it('does the same from the page itself, where a fresh tab starts', () => {
    const { actions } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: 'Enter' })
    expect(spies.toggleRunFocus).toHaveBeenCalledOnce()
  })

  it('puts a held run down again, which is the same key', () => {
    const { actions } = catalogue()
    mount(actions, true)

    fireEvent.keyDown(list(), { key: 'Enter' })
    expect(spies.toggleRunFocus).toHaveBeenCalledOnce()
  })

  it('belongs to whatever has focus outside the list', () => {
    const { actions } = catalogue()
    mount(actions)

    fireEvent.keyDown(panel(), { key: 'Enter' })
    expect(spies.toggleRunFocus).not.toHaveBeenCalled()
  })
})

/* -------------------------------------------------------------------- */
/* ...and what `↑`/`↓` mean while one is held                            */
/* -------------------------------------------------------------------- */

describe('while a run is focused', () => {
  it('moves the run with `↑`/`↓` and `j`/`k`, and never the selection', () => {
    const { actions } = catalogue()
    mount(actions, true)

    fireEvent.keyDown(document.body, { key: 'ArrowDown' })
    fireEvent.keyDown(document.body, { key: 'j' })
    fireEvent.keyDown(document.body, { key: 'ArrowUp' })
    fireEvent.keyDown(document.body, { key: 'k' })

    expect(spies.moveRun.mock.calls).toEqual([[1], [1], [-1], [-1]])
    expect(spies.select).not.toHaveBeenCalled()
  })

  it('moves nothing while no run is held, which is the other half', () => {
    const { actions } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: 'ArrowDown' })
    fireEvent.keyDown(document.body, { key: 'k' })

    expect(spies.select.mock.calls).toEqual([[1], [-1]])
    expect(spies.moveRun).not.toHaveBeenCalled()
  })

  it('leaves every other key of the map exactly as it was', () => {
    const { actions, ran } = catalogue()
    mount(actions, true)

    fireEvent.keyDown(document.body, { key: 'ArrowRight' })
    fireEvent.keyDown(document.body, { key: '1' })
    fireEvent.keyDown(document.body, { key: 'n' })

    expect(spies.cyclePane.mock.calls).toEqual([[1]])
    expect(spies.jumpPane.mock.calls).toEqual([[0]])
    expect(ran).toEqual(['new-run'])
    expect(spies.moveRun).not.toHaveBeenCalled()
  })

  it('moves nothing from inside an input, or under an overlay', () => {
    const { actions } = catalogue()
    mount(actions, true)

    fireEvent.keyDown(filter(), { key: 'ArrowDown' })
    expect(spies.moveRun).not.toHaveBeenCalled()

    released.push(claimKeyboard())
    fireEvent.keyDown(document.body, { key: 'ArrowUp' })
    expect(spies.moveRun).not.toHaveBeenCalled()
    expect(spies.select).not.toHaveBeenCalled()
  })

  it('is put down by `esc`, which the shell reads as its `close`', () => {
    const { actions } = catalogue()
    mount(actions, true)

    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(spies.close).toHaveBeenCalledOnce()
  })
})

/* -------------------------------------------------------------------- */
/* Scoping                                                               */
/* -------------------------------------------------------------------- */

describe('inside an input', () => {
  it('suppresses every shortcut, which is what `D` exists for', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    for (const key of ['d', 'D', 'n', 'j', 'a', '1']) {
      fireEvent.keyDown(filter(), { key })
    }

    nothingHappened(ran)
  })

  it('suppresses them in a textarea and a contenteditable too', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    fireEvent.keyDown(screen.getByRole('textbox', { name: 'a note' }), { key: 'n' })
    fireEvent.keyDown(screen.getByLabelText('a document'), { key: 'n' })

    nothingHappened(ran)
  })

  it('still closes on `esc`, and still takes the chords', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    fireEvent.keyDown(filter(), { key: 'Escape' })
    expect(spies.close).toHaveBeenCalledOnce()

    fireEvent.keyDown(filter(), { key: 'r', ctrlKey: true })
    expect(ran).toEqual(['refresh'])
  })

  it('suppresses them inside a rich editor’s own markup', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    // `closest`, so a keystroke from a node *inside* an editable region
    // counts as typing too — which is where the caret usually is.
    const inside = document.createElement('strong')
    screen.getByLabelText('a document').append(inside)
    fireEvent.keyDown(inside, { key: 'n' })

    nothingHappened(ran)
  })

  it('suppresses them where the browser alone reports editability', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    // A browser sets `isContentEditable` on every node of an editable
    // subtree, inherited included; jsdom implements neither that
    // property nor contenteditable, so it is stated here.
    const editor = list()
    Object.defineProperty(editor, 'isContentEditable', {
      configurable: true,
      value: true,
    })
    fireEvent.keyDown(editor, { key: 'n' })

    nothingHappened(ran)
  })

})

describe('a keystroke that came from no element at all', () => {
  it('is nobody’s typing, and belongs to no region', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    // A key pressed on the page has `document.body` as its target; this
    // is the synthetic case, and the map answers it by what it can see.
    for (const key of ['n', 'Enter', 'a']) {
      window.dispatchEvent(new KeyboardEvent('keydown', { key, cancelable: true }))
    }

    // `n` is the app's own and runs. `⏎` and `a` are both scoped to
    // somewhere — the run list, a request panel — and a target that is
    // in neither is in neither, so they do nothing rather than firing
    // from wherever the last focus happened to be.
    expect(ran).toEqual(['new-run'])
    expect(spies.toggleRunFocus).not.toHaveBeenCalled()
    expect(allow).not.toHaveBeenCalled()
  })
})

describe('while an overlay owns the keyboard', () => {
  beforeEach(() => {
    released.push(claimKeyboard())
  })

  it('suppresses the app’s own keys', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    for (const key of ['n', 'D', 'j', 'a', '1']) {
      fireEvent.keyDown(document.body, { key })
    }

    nothingHappened(ran)
  })

  it('leaves `esc` and the chords, which are how it is left', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(spies.close).toHaveBeenCalledOnce()

    fireEvent.keyDown(document.body, { key: 'p', ctrlKey: true })
    expect(spies.openPalette).toHaveBeenCalledOnce()

    fireEvent.keyDown(document.body, { key: 'r', ctrlKey: true })
    expect(ran).toEqual(['refresh'])
  })
})

describe('`a` and `d`', () => {
  it('answer only with the request panel focused', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    fireEvent.keyDown(screen.getByRole('button', { name: 'Allow once' }), { key: 'a' })
    expect(allow).toHaveBeenCalledOnce()

    fireEvent.keyDown(panel(), { key: 'd' })
    expect(deny).toHaveBeenCalledOnce()
    expect(ran).toEqual([])
  })

  it('do nothing at all from the run list', () => {
    // The whole of D51: a `d` meant for "deny" that lands one focus ring
    // away must not reach the delete confirm, and it does not reach
    // anything else either.
    const { actions, ran } = catalogue()
    mount(actions)

    fireEvent.keyDown(list(), { key: 'd' })
    fireEvent.keyDown(list(), { key: 'a' })

    nothingHappened(ran)
  })

  it('are the panel’s own and not the run list’s `D`', () => {
    const { actions, ran } = catalogue()
    mount(actions)

    // `D` is the app's wherever it is pressed outside an input, and the
    // panel does not swallow it.
    fireEvent.keyDown(panel(), { key: 'D', shiftKey: true })
    expect(ran).toEqual(['delete-run'])
    expect(deny).not.toHaveBeenCalled()
  })
})
