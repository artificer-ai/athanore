/**
 * The accessibility gate on the dashboard
 * (`docs/v1/17-serial-task-plan.md` § T068a, 10 §Accessibility and
 * quality).
 *
 * Five states of the one page, because they are five different
 * documents: the dashboard an operator opens — an empty list and the
 * global inbox — the dashboard they work in, with a run selected, a
 * graph drawn and a request waiting to be answered, that same dashboard
 * at the largest step of the type ramp, that same dashboard on a phone —
 * all three of its narrow screens — and the run list with a `failed` run
 * selected. Everything the mock puts on screen is in the second one.
 *
 * The third and the fourth are D197's, which is one floor over three
 * documents: `xlarge` is a 25 % larger base under a layout specified in
 * pixels, which is where text would overlap its chrome or be clipped out
 * of its box if anything in the app had assumed the mock's 12 px (21
 * §Type scale); 390×844 is the narrow layout, where the regions are
 * different elements — one stacked middle, a back control, two-line
 * rows, a scrolling header strip — and therefore a different tree for
 * axe to walk (21 §Narrow layout).
 *
 * The fifth is the selected row's tint under the darkest pill.
 * `StatusPill` is transparent — it paints `text-status-*` straight onto
 * whatever the row is tinted with — and `fail` (`#d9868f`) is the
 * darkest of the seven tones of 10 §Status colours and therefore the
 * one that decides the floor (D204 (5)). The second state selects a
 * `probe` run, which is never `failed`, so without this one the ratio
 * that matters most is argued rather than measured.
 *
 * The scoring is `support/a11y.ts`'s, and the reason it is written down
 * rather than taken off a tool is there (D178).
 */
import AxeBuilder from '@axe-core/playwright'

import { A11Y_SCORE, axeScore, blocking, violationReport } from './support/a11y'
import { expect, NARROW_VIEWPORT, test } from './support/fixtures'

test('the empty dashboard passes the a11y gate', async ({ dashboard }) => {
  await dashboard.open()

  const results = await new AxeBuilder({ page: dashboard.page }).analyze()

  expect(blocking(results), violationReport(results)).toEqual([])
  expect(axeScore(results), violationReport(results)).toBeGreaterThanOrEqual(A11Y_SCORE)
})

test('the dashboard with a run, a graph and a request passes it too', async ({
  dashboard,
}) => {
  await dashboard.open()
  await dashboard.submit('probe', 'read me with a screen reader')
  await dashboard.select('read me with a screen reader')
  await dashboard.pane('graph')
  await expect(dashboard.graphRow('draft')).toBeVisible()
  await dashboard.pane('requests')
  await expect(dashboard.openRequest('permission')).toBeVisible()

  const results = await new AxeBuilder({ page: dashboard.page }).analyze()

  expect(blocking(results), violationReport(results)).toEqual([])
  expect(axeScore(results), violationReport(results)).toBeGreaterThanOrEqual(A11Y_SCORE)
})

test('the same dashboard passes it at the largest type step', async ({
  dashboard,
}) => {
  await dashboard.open()
  await dashboard.submit('probe', 'read me at xlarge')
  await dashboard.select('read me at xlarge')
  await dashboard.chooseFontSize('xlarge')
  await dashboard.pane('graph')
  await expect(dashboard.graphRow('draft')).toBeVisible()
  await dashboard.pane('requests')
  await expect(dashboard.openRequest('permission')).toBeVisible()

  const results = await new AxeBuilder({ page: dashboard.page }).analyze()

  expect(blocking(results), violationReport(results)).toEqual([])
  expect(axeScore(results), violationReport(results)).toBeGreaterThanOrEqual(A11Y_SCORE)
})

test('a failed run selected in the list passes it too', async ({ dashboard }) => {
  await dashboard.open()
  await dashboard.submitOverApi('flop', 'read me while I am selected')
  await expect(dashboard.status('read me while I am selected')).toHaveText('failed')

  await dashboard.select('read me while I am selected')
  // The click that selected the row left the pointer on it, and
  // `hover:bg-*` outranks the row's own tint — axe would measure the
  // hover colour and the selected one would go unmeasured.
  await dashboard.page.mouse.move(0, 0)
  // The state axe is about is the row's, so it is asserted before axe
  // walks the page rather than assumed from the click.
  await expect(dashboard.row('read me while I am selected')).toHaveAttribute(
    'aria-selected',
    'true',
  )

  const results = await new AxeBuilder({ page: dashboard.page }).analyze()

  expect(blocking(results), violationReport(results)).toEqual([])
  expect(axeScore(results), violationReport(results)).toBeGreaterThanOrEqual(A11Y_SCORE)
})

test.describe('on a phone', () => {
  test.use({ viewport: NARROW_VIEWPORT, hasTouch: true, isMobile: true })

  test('the loaded dashboard passes it at 390×844', async ({ dashboard }) => {
    await dashboard.open()
    await dashboard.submit('probe', 'read me on a phone', 'tap')
    // The narrow shell shows one region at a time, so this walks both:
    // the run list, then the detail the row opens onto.
    const results = await new AxeBuilder({ page: dashboard.page }).analyze()
    expect(blocking(results), violationReport(results)).toEqual([])
    expect(axeScore(results), violationReport(results)).toBeGreaterThanOrEqual(
      A11Y_SCORE,
    )

    await dashboard.row('read me on a phone').tap()
    await dashboard.page.locator('[data-pane="requests"][role="radio"]').tap()
    await expect(dashboard.openRequest('permission')).toBeVisible()

    const detail = await new AxeBuilder({ page: dashboard.page }).analyze()
    expect(blocking(detail), violationReport(detail)).toEqual([])
    expect(axeScore(detail), violationReport(detail)).toBeGreaterThanOrEqual(A11Y_SCORE)

    // ...and the third narrow screen: the global panes, beside the list
    // (D218), with the same request waiting in the inbox (D216).
    await dashboard.back().tap()
    await expect(dashboard.page.locator('main[data-stacked="list"]')).toBeVisible()
    await dashboard.globalPanes().tap()
    await expect(dashboard.page.locator('main[data-stacked="global"]')).toBeVisible()
    await expect(dashboard.openRequest('permission')).toBeVisible()

    const global = await new AxeBuilder({ page: dashboard.page }).analyze()
    expect(blocking(global), violationReport(global)).toEqual([])
    expect(axeScore(global), violationReport(global)).toBeGreaterThanOrEqual(A11Y_SCORE)
  })
})
