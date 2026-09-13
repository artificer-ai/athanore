/**
 * The dashboard on a phone: the six flows of `docs/v1/21-design-refresh.md`
 * §Touch operation, and every overlay of 10 §Overlays, at 390×844 with a
 * finger (T082, D194, D197, D216, D218).
 *
 * **Everything here is a `tap()`.** A `click()` that passes says nothing
 * about whether a touch device can operate the app: it is dispatched at
 * a point rather than through the touch pipeline, and it reaches a
 * control no finger could hit. The context carries `hasTouch` and
 * `isMobile` for the same reason — `isMobile` is what makes the browser
 * lay the page out as a phone does, viewport meta and all.
 *
 * Typing is the exception 21 names: an on-screen keyboard into a focused
 * input is not a keyboard shortcut, so `fill()` after a `tap()` is the
 * operator's own gesture and not a way round the gate.
 *
 * One viewport, not a matrix. 360 px is covered by 21's fluid rule —
 * asserted here as `scrollWidth <= innerWidth` in every state — rather
 * than by a second run of the same assertions against the same CSS.
 */
import type { Locator, Page } from '@playwright/test'

import { expect, NARROW_VIEWPORT, RUN_TIMEOUT, test } from './support/fixtures'

test.use({ viewport: NARROW_VIEWPORT, hasTouch: true, isMobile: true })

const TITLE = 'answer me with a thumb'

/** The run of the eight-rank fixture, read on the graph canvas. */
const TALL_TITLE = 'eight rungs on a thumb'

/** WCAG 2.5.8, which 21 §Regions, narrow asks of the narrow chrome. */
const TOUCH_TARGET = 24

/** The page itself never scrolls sideways (21 §Narrow layout). */
async function noHorizontalScroll(page: Page): Promise<void> {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    ),
  ).toBeLessThanOrEqual(0)
}

/** Every edge of `locator` is inside the viewport, and the page is still. */
async function contained(page: Page, locator: Locator): Promise<void> {
  const box = await locator.boundingBox()
  expect(box, 'the panel has no box').not.toBeNull()
  if (box === null) return
  expect(box.x, 'left edge').toBeGreaterThanOrEqual(0)
  expect(box.y, 'top edge').toBeGreaterThanOrEqual(0)
  expect(box.x + box.width, 'right edge').toBeLessThanOrEqual(NARROW_VIEWPORT.width)
  expect(box.y + box.height, 'bottom edge').toBeLessThanOrEqual(NARROW_VIEWPORT.height)
  await noHorizontalScroll(page)
}

/** A control a finger has to be able to hit. */
async function tappable(locator: Locator): Promise<void> {
  const box = await locator.boundingBox()
  expect(box, 'the control has no box').not.toBeNull()
  if (box === null) return
  expect(box.width, 'hit area width').toBeGreaterThanOrEqual(TOUCH_TARGET)
  expect(box.height, 'hit area height').toBeGreaterThanOrEqual(TOUCH_TARGET)
}

test('the five touch flows: list, detail, panes, an answer, a new run', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()

  // -- flow 5, first, because the other four need a run: start one from
  //    `＋ new run`. The chip is tapped, the title typed into a focused
  //    input (21: the on-screen keyboard is not a shortcut), and
  //    `submit run` tapped.
  await page.getByRole('button', { name: 'new run', exact: true }).tap()
  const newRun = page.getByTestId('new-run')
  await expect(newRun).toBeVisible()
  await contained(page, newRun)
  // With the form empty, both footer buttons are on screen already.
  await expect(newRun.getByRole('button', { name: 'submit run' })).toBeInViewport()
  await expect(newRun.getByRole('button', { name: 'cancel' })).toBeInViewport()
  await newRun.getByRole('radio', { name: 'probe', exact: true }).tap()
  await newRun.locator('#new-run-title').tap()
  await newRun.locator('#new-run-title').fill(TITLE)
  await newRun.getByRole('button', { name: 'submit run' }).tap()
  await expect(newRun).toBeHidden()

  // -- flow 1: the run list is the middle region, and the new run is in
  //    it as the two-line row of 21 §Narrow layout.
  const row = dashboard.row(TITLE)
  await expect(row).toBeVisible()
  await expect(row.getByTestId('narrow-title')).toHaveText(TITLE)
  await expect(row.getByTestId('narrow-meta')).toContainText('probe')
  await tappable(row)
  await noHorizontalScroll(page)

  // -- flow 2: tapping the row opens the detail, which is now the whole
  //    middle; the back control puts the list back.
  await row.tap()
  const detail = page.locator('[data-region="detail"]')
  await expect(detail).toBeVisible()
  await expect(page.locator('[data-region="list"]')).toHaveCount(0)
  expect((await detail.boundingBox())?.width).toBe(NARROW_VIEWPORT.width)
  await noHorizontalScroll(page)

  await tappable(dashboard.back())
  await dashboard.back().tap()
  await expect(page.locator('[data-region="list"]')).toBeVisible()
  await expect(page.locator('[data-region="detail"]')).toHaveCount(0)
  expect(new URL(page.url()).searchParams.get('run')).toBeNull()
  await noHorizontalScroll(page)

  // -- flow 3: back into the run, and round the pane cycle with `▶`
  //    alone. The label advances and wraps.
  await row.tap()
  await expect(dashboard.paneLabel()).toHaveText(/OVERVIEW \(1\/(\d+)\)/)
  const label = await dashboard.paneLabel().textContent()
  const count = Number(/\((\d+)\/(\d+)\)/.exec(label ?? '')?.[2])
  expect(count).toBeGreaterThan(1)
  await tappable(dashboard.nextPane())
  // Every dot is a hit area in its own right: the 14×3 px bar is the
  // mark, and the box around it is what a finger lands on (D201 (4)).
  const dots = page.locator('[data-pane][role="radio"]')
  await expect(dots).toHaveCount(count)
  for (const dot of await dots.all()) {
    await tappable(dot)
  }
  // Measured on every pane, not only where the cycle wraps: 21 §Narrow
  // layout says no horizontal scroll in *any* of these flows, and each
  // pane draws different content into the same width.
  await noHorizontalScroll(page)
  for (let i = 2; i <= count; i += 1) {
    await dashboard.nextPane().tap()
    await expect(dashboard.paneLabel()).toHaveText(
      new RegExp(`\\(${String(i)}/${String(count)}\\)`),
    )
    await noHorizontalScroll(page)
  }
  await dashboard.nextPane().tap()
  await expect(dashboard.paneLabel()).toHaveText(new RegExp(`\\(1/${String(count)}\\)`))
  await noHorizontalScroll(page)

  // -- flow 4: the request the agent is waiting on, answered by tapping
  //    the option the server offered — by its id, never by position
  //    (D10). The pane is reached by the dots, which are the same touch
  //    route the arrows are.
  await page.locator('[data-pane="requests"][role="radio"]').tap()
  const permission = dashboard.openRequest('permission')
  await expect(permission).toBeVisible({ timeout: RUN_TIMEOUT })
  await contained(page, permission)
  const answered = await dashboard.answer(permission, 'allow', 'tap')
  await expect(answered.getByTestId('request-author')).toHaveText('user')

  // The node after it asks the operator a question of its own, which is
  // the second kind 21 §Touch operation names.
  const question = dashboard.openRequest('question')
  await expect(question).toBeVisible({ timeout: RUN_TIMEOUT })
  await dashboard.answer(question, 'ship', 'tap')
  await dashboard.back().tap()
  await expect(dashboard.status(TITLE)).toHaveText('completed', {
    timeout: RUN_TIMEOUT,
  })
  await noHorizontalScroll(page)
})

test('the sixth touch flow: the three screens — global | list | detail — and the swipes between them', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  // `probe`'s first node asks for a permission, which lands in the inbox
  // — the one global pane every build has (09 §Builtins) and the one
  // that was unreachable at this width before D216.
  await dashboard.submit('probe', TITLE, 'tap')
  const row = dashboard.row(TITLE)
  await expect(row).toBeVisible()

  // -- the list is the middle of the row (D218): a swipe left would be
  //    the detail, which is never swiped to — a run is chosen by tapping
  //    its row — so the list stays.
  const list = page.locator('main[data-stacked="list"]')
  await expect(list).toBeVisible()
  await dashboard.swipe('left')
  await expect(list).toBeVisible()
  expect(new URL(page.url()).searchParams.get('run')).toBeNull()
  expect(new URL(page.url()).searchParams.get('global')).toBeNull()
  await noHorizontalScroll(page)

  // -- the button: the discoverable route (21 §Touch operation: nothing
  //    reachable only via a gesture), drawn on the list and the global
  //    screen — the two the swipe joins.
  await tappable(dashboard.globalPanes())
  await expect(dashboard.globalPanes()).toHaveAttribute('aria-pressed', 'false')
  await dashboard.globalPanes().tap()
  const global = page.locator('main[data-stacked="global"]')
  await expect(global).toBeVisible()
  await expect(dashboard.globalPanes()).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('pane-body')).toHaveAttribute(
    'data-pane',
    '_builtin:inbox',
  )
  await expect(dashboard.paneLabel()).toHaveText(/INBOX \(1\/\d+\)/)
  // Nothing is selected — the screen sits beside the list; `?global=`
  // is up.
  let url = new URL(page.url())
  expect(url.searchParams.get('run')).toBeNull()
  expect(url.searchParams.get('global')).toBe('0')
  await contained(page, page.locator('[data-region="detail"]'))

  // -- the controls work from here: the permission is answered in the
  //    inbox, by tapping the option the server offered (D10).
  const permission = dashboard.openRequest('permission')
  await expect(permission).toBeVisible({ timeout: RUN_TIMEOUT })
  await expect(page.getByTestId('pane-inbox')).toBeVisible()
  await contained(page, permission)
  await dashboard.answer(permission, 'allow', 'tap')
  // The inbox holds open requests only, so the answer shows as the next
  // thing the run asks: the node after it puts a question to the
  // operator, which lands here too.
  await expect(dashboard.openRequest('question')).toBeVisible({ timeout: RUN_TIMEOUT })
  await noHorizontalScroll(page)

  // -- `←` in the bar: back to the list, labelled as the detail's is
  //    because both go there (D218).
  await tappable(dashboard.back())
  await dashboard.back().tap()
  await expect(list).toBeVisible()
  await expect(row).toBeVisible()
  url = new URL(page.url())
  expect(url.searchParams.get('global')).toBeNull()
  expect(url.searchParams.get('run')).toBeNull()
  await noHorizontalScroll(page)

  // -- the gesture, from the list: a swipe right reaches the global
  //    screen; another swipe right there is the row's end and moves
  //    nothing; a swipe left puts the screen away.
  await dashboard.swipe('right')
  await expect(global).toBeVisible()
  await expect(dashboard.paneLabel()).toHaveText(/INBOX/)
  await noHorizontalScroll(page)
  await dashboard.swipe('right')
  await expect(global).toBeVisible()
  await expect(dashboard.paneLabel()).toHaveText(/INBOX/)
  await dashboard.swipe('left')
  await expect(list).toBeVisible()
  await expect(row).toBeVisible()
  expect(new URL(page.url()).searchParams.get('global')).toBeNull()
  await noHorizontalScroll(page)

  // -- a swipe that starts in the edge is the browser's, not ours: the
  //    list stays, and the global screen is not opened.
  await dashboard.swipe('right', 8)
  await expect(list).toBeVisible()
  await expect(global).toHaveCount(0)
  await noHorizontalScroll(page)

  // -- the detail: reached only by a tap; no `global panes` button, a
  //    swipe left is the row's other end, and a swipe right is the `←`
  //    — the list, with nothing selected.
  await row.tap()
  const detail = page.locator('main[data-stacked="detail"]')
  await expect(detail).toBeVisible()
  const runId = new URL(page.url()).searchParams.get('run')
  expect(runId).not.toBeNull()
  await expect(dashboard.globalPanes()).toHaveCount(0)
  await dashboard.nextPane().tap()
  await expect(dashboard.paneLabel()).toHaveText(/\(2\/\d+\)/)
  await dashboard.swipe('left')
  await expect(detail).toBeVisible()
  await expect(dashboard.paneLabel()).toHaveText(/\(2\/\d+\)/)
  expect(new URL(page.url()).searchParams.get('run')).toBe(runId)
  await noHorizontalScroll(page)
  await dashboard.swipe('right')
  await expect(list).toBeVisible()
  await expect(row).toBeVisible()
  await expect(dashboard.back()).toHaveCount(0)
  url = new URL(page.url())
  expect(url.searchParams.get('run')).toBeNull()
  expect(url.searchParams.get('global')).toBeNull()
  await noHorizontalScroll(page)
})

test('the narrow chrome: header strip, footer, hit areas', async ({ dashboard }) => {
  const page = dashboard.page
  await dashboard.open()
  await dashboard.submit('probe', TITLE, 'tap')

  // The chips and the `/` filter are one strip on a line of their own,
  // scrolling within themselves — the page does not.
  const filter = page.getByRole('textbox', { name: 'filter runs' })
  const chips = page.getByRole('radiogroup', { name: 'filter by workflow' })
  const strip = page.locator('header > div').filter({ has: chips })
  await expect(strip).toBeVisible()
  await expect(strip).toContainText('probe')
  expect((await strip.boundingBox())?.width).toBeLessThanOrEqual(
    NARROW_VIEWPORT.width,
  )
  // The strip scrolls sideways within itself; the page does not.
  expect(
    await strip.evaluate((el) => el.scrollWidth >= el.clientWidth),
  ).toBe(true)
  await expect(filter).toBeVisible()
  await expect(page.getByRole('button', { name: 'new run', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'workflows' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'text size' })).toBeVisible()
  for (const name of ['new run', 'workflows', 'text size']) {
    await tappable(page.getByRole('button', { name, exact: name === 'new run' }))
  }
  await tappable(page.getByRole('radio', { name: 'probe', exact: true }))

  // The footer keeps the palette button and drops the keycaps.
  const palette = page.getByRole('button', { name: 'palette' })
  await expect(palette).toBeVisible()
  await tappable(palette)
  await expect(page.locator('footer kbd').first()).toBeHidden()

  // The list footer keeps `n shown` and drops the key hints.
  await expect(page.getByTestId('rows-shown')).toBeVisible()
  await expect(page.getByText('↑↓ select')).toBeHidden()

  // The keyboard map is still bound at this width: `n` opens New Run.
  await page.keyboard.press('n')
  await expect(page.getByTestId('new-run')).toBeVisible()
  await page.keyboard.press('Escape')

  await noHorizontalScroll(page)
})

test('every overlay opens by touch, fits the viewport and closes by touch', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  await dashboard.submit('probe', TITLE, 'tap')
  await dashboard.row(TITLE).tap()

  /** Open an overlay, assert it fits, and dismiss it by touch. */
  const sweep = async (
    testId: string,
    open: () => Promise<void>,
    dismiss: 'close' | 'backdrop',
  ) => {
    await open()
    const panel = page.getByTestId(testId)
    await expect(panel).toBeVisible()
    await contained(page, panel)
    if (dismiss === 'close') {
      const close = dashboard.overlayClose(panel)
      await tappable(close)
      await close.tap()
    } else {
      // The backdrop is the whole screen behind the panel; its top-left
      // corner is outside every panel this app draws.
      await page.getByTestId(`${testId}-backdrop`).tap({ position: { x: 4, y: 4 } })
    }
    await expect(panel).toBeHidden()
    await noHorizontalScroll(page)
  }

  await sweep('palette', async () => void (await dashboard.tapPalette()), 'close')
  await sweep(
    'new-run',
    () => page.getByRole('button', { name: 'new run', exact: true }).tap(),
    'backdrop',
  )
  await sweep(
    'library',
    () => page.getByRole('button', { name: 'workflows' }).tap(),
    'close',
  )
  await sweep('edit-run', () => dashboard.tapCommand('edit run'), 'close')
  await sweep('keys', () => dashboard.tapCommand('keys'), 'close')
  await sweep('delete-run', () => dashboard.tapCommand('delete run'), 'backdrop')
  await sweep('picker', () => dashboard.tapCommand('retry task'), 'close')
  await sweep('picker', () => dashboard.tapCommand('move task'), 'close')
  await sweep('picker', () => dashboard.tapCommand('cancel task'), 'close')
  await sweep('picker', () => dashboard.tapCommand('rerun node'), 'close')

  // The task drawer is a full-screen sheet, opened from a NODES row of
  // the overview (10 §Overlays), which is where the only route to it is.
  await sweep(
    'task-drawer',
    () => page.locator('[data-testid="node-rows"] button[data-node]').first().tap(),
    'close',
  )

  // The action overlay has no touch route on these fixtures — no
  // workflow here declares an action, so the palette lists none (09
  // §Declarations) — so it is opened as a link and dismissed by touch,
  // which is the half of the sweep that is about the narrow viewport.
  const runId = new URL(page.url()).searchParams.get('run') ?? ''
  await sweep(
    'plugin-action',
    async () => {
      await page.goto(
        `${dashboard.server.url}/?run=${runId}&overlay=action&action=none%3Anone`,
      )
      // `?run=` is set, so the middle is the detail: the run list is
      // not on this screen to wait for (21 §Narrow layout).
      await expect(page.getByTestId('pane-label')).toBeVisible()
    },
    'close',
  )
})

test('the graph canvas is a fitted picture below the breakpoint', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  await dashboard.submit('probe', TITLE, 'tap')
  await dashboard.row(TITLE).tap()
  await page.locator('[data-pane="graph"][role="radio"]').tap()

  // The cards are drawn and reachable, so the pane says what the run is
  // doing at 390 px as it does at 1440 (10 §Graph pane).
  await expect(dashboard.graphRow('draft')).toBeVisible({ timeout: RUN_TIMEOUT })
  await tappable(dashboard.graphRow('draft'))

  // No pan, no zoom, and therefore no control strip: below the
  // breakpoint the canvas is a picture, and the EDGES block underneath
  // carries the detail (21 §Narrow layout, D206 (7)).
  await expect(page.getByTestId('rf__controls')).toHaveCount(0)
  const edges = page.getByTestId('graph-legend-row').first()
  await expect(edges).toBeVisible()
  const canvas = page.locator('.react-flow')
  const canvasBox = await canvas.boundingBox()
  const edgesBox = await edges.boundingBox()
  expect(canvasBox, 'the canvas has no box').not.toBeNull()
  expect(edgesBox, 'the EDGES block has no box').not.toBeNull()
  if (canvasBox !== null && edgesBox !== null) {
    expect(edgesBox.y, 'EDGES sits under the canvas').toBeGreaterThanOrEqual(
      canvasBox.y + canvasBox.height,
    )
  }

  await noHorizontalScroll(page)
})

test('a tall graph is fitted whole below the breakpoint, not clipped', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  // `ladder` is eight ranks (`./workflows.py`), which is taller than a
  // 320 px canvas can draw at the zoom the pane's interaction floor
  // allows. Below the breakpoint there is nothing to recover a clipped
  // picture with — no pan, no pinch, no controls — so the fit carries a
  // floor of its own and the whole graph shrinks to fit (D206 (7)).
  await dashboard.submit('ladder', TALL_TITLE, 'tap')
  await dashboard.row(TALL_TITLE).tap()
  await page.locator('[data-pane="graph"][role="radio"]').tap()

  const first = dashboard.graphRow('intake')
  const last = dashboard.graphRow('label')
  await expect(first).toBeVisible({ timeout: RUN_TIMEOUT })
  await expect(last).toBeVisible()

  const canvasBox = await page.locator('.react-flow').boundingBox()
  expect(canvasBox, 'the canvas has no box').not.toBeNull()
  if (canvasBox === null) return
  for (const [which, card] of [
    ['the first', first],
    ['the last', last],
  ] as const) {
    const box = await card.boundingBox()
    expect(box, `${which} card has no box`).not.toBeNull()
    if (box === null) continue
    // Half a pixel of tolerance: the canvas draws through a fractional
    // CSS transform, and what is being asserted is a whole card inside
    // the frame rather than a rounding.
    expect(box.y, `${which} card's top edge`).toBeGreaterThanOrEqual(canvasBox.y - 0.5)
    expect(box.y + box.height, `${which} card's bottom edge`).toBeLessThanOrEqual(
      canvasBox.y + canvasBox.height + 0.5,
    )
    expect(box.x, `${which} card's left edge`).toBeGreaterThanOrEqual(canvasBox.x - 0.5)
    expect(box.x + box.width, `${which} card's right edge`).toBeLessThanOrEqual(
      canvasBox.x + canvasBox.width + 0.5,
    )
  }

  await noHorizontalScroll(page)
})
