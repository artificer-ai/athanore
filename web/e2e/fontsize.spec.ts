/**
 * The font-size chooser, in a browser
 * (`docs/v1/21-design-refresh.md` §Type scale, D195, D196).
 *
 * `src/store/__tests__/prefs.test.ts` already drives the preference and
 * `src/styles/theme.test.ts` already reads the generated ramp; what only
 * a browser can say is that the two meet — that choosing `xlarge` from
 * the header really rescales a metric value and a table row *together*,
 * that the choice survives a reload, and that clearing site data brings
 * the design's own base back.
 *
 * The numbers are exact rather than "bigger": the ramp is fractions of
 * the base (`text-metric` 15/12, `text-row` 11.5/12), so at `xlarge`'s
 * 15 px base they resolve to 18.75 px and 14.375 px and nothing else. A
 * mixed-scale step would be a rounding away from these, not a doubling.
 */
import { expect, test } from './support/fixtures'

/** `<html>`, whose `font-size` the whole ramp is a fraction of. */
const HTML = 'html'

test('the header chooser rescales the whole ramp, and it survives a reload', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  await dashboard.submit('probe', 'read me larger')
  await dashboard.select('read me larger')
  await dashboard.pane('overview')

  const metric = page.locator('[data-testid="metric-grid"] dd').first()
  const row = dashboard.row('read me larger')
  // The two sizes written at a call site rather than in the ramp, each
  // beside a size that is in it: the status pill inside that row, and a
  // workflow chip in the header beside the run counts. Absolute pixels
  // here are invisible at the default base and are the mixed-scale text
  // 21 §Type scale forbids at every other step.
  const pill = dashboard.status('read me larger')
  const chip = page.locator('header').getByRole('radio', { name: 'all' })
  const meta = page.getByTestId('header-counts')
  await expect(metric).toBeVisible()

  // The default base is the design's: no attribute, and the mock's
  // pixel sizes to the decimal.
  await expect(page.locator(HTML)).not.toHaveAttribute('data-font-size', /./)
  expect(await dashboard.fontSize(page.locator(HTML))).toBe(12)
  expect(await dashboard.fontSize(metric)).toBe(15)
  expect(await dashboard.fontSize(row)).toBe(11.5)
  expect(await dashboard.fontSize(pill)).toBe(10.5)
  expect(await dashboard.fontSize(chip)).toBe(10.5)
  expect(await dashboard.fontSize(meta)).toBe(11)

  await dashboard.chooseFontSize('xlarge')

  // One attribute, and every step of the ramp moved with the base.
  expect(await dashboard.fontSize(page.locator(HTML))).toBe(15)
  expect(await dashboard.fontSize(metric)).toBe(18.75)
  expect(await dashboard.fontSize(row)).toBe(14.375)

  // Including the text no utility of the ramp names: the pill grew with
  // the row it sits in (10.5/12 × 15), the chip with the counts beside
  // it (11/12 × 15). Text at two scales in one row is what 21 §Type
  // scale forbids, and it is what an absolute `px` at a call site does.
  expect(await dashboard.fontSize(pill)).toBe(13.125)
  expect(await dashboard.fontSize(chip)).toBe(13.125)
  expect(await dashboard.fontSize(meta)).toBe(13.75)

  // Density did not (D195, D199). `--spacing` is pinned to the 3 px
  // Tailwind's `0.25rem` step resolves to at the mock's base, so the
  // header's own `gap-y-2` is 6 px here as it is at every other step —
  // without the pin it would be 7.5 px.
  const headerRowGap = await page
    .locator('header')
    .evaluate((element) => getComputedStyle(element).rowGap)
  expect(headerRowGap).toBe('6px')

  // A full reload: the choice is in `athanore.prefs` and is on the
  // document before the app is interactive.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'ATHANORE' })).toBeVisible()
  await expect(page.locator(HTML)).toHaveAttribute('data-font-size', 'xlarge')
  expect(await dashboard.fontSize(page.locator(HTML))).toBe(15)

  // Clearing site data restores the design's default base.
  await page.evaluate(() => {
    localStorage.clear()
  })
  await page.reload()
  await expect(page.getByRole('heading', { name: 'ATHANORE' })).toBeVisible()
  await expect(page.locator(HTML)).not.toHaveAttribute('data-font-size', /./)
  expect(await dashboard.fontSize(page.locator(HTML))).toBe(12)
})

test('every step of the chooser is a base of its own, from the palette too', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()

  // The palette's four rows are the same choice without a pointer
  // (D196); `^p` reaches them with nothing selected.
  await dashboard.command('font size: small')
  await expect(page.locator(HTML)).toHaveAttribute('data-font-size', 'small')
  expect(await dashboard.fontSize(page.locator(HTML))).toBe(11)

  await dashboard.command('font size: large')
  expect(await dashboard.fontSize(page.locator(HTML))).toBe(13.5)

  // Back to the design's base: the row and the absence of the attribute
  // are the same state as never having chosen at all.
  await dashboard.command('font size: default')
  await expect(page.locator(HTML)).not.toHaveAttribute('data-font-size', /./)
  expect(await dashboard.fontSize(page.locator(HTML))).toBe(12)
})
