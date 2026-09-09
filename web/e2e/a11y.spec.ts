/**
 * The accessibility gate on the dashboard
 * (`docs/v1/17-serial-task-plan.md` § T068a, 10 §Accessibility and
 * quality).
 *
 * Two states of the one page, because they are two different documents:
 * the dashboard an operator opens — an empty list and the global inbox —
 * and the dashboard they work in, with a run selected, a graph drawn and
 * a request waiting to be answered. Everything the mock puts on screen
 * is in the second one.
 *
 * The scoring is `support/a11y.ts`'s, and the reason it is written down
 * rather than taken off a tool is there (D178).
 */
import AxeBuilder from '@axe-core/playwright'

import { A11Y_SCORE, axeScore, blocking, violationReport } from './support/a11y'
import { expect, test } from './support/fixtures'

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
