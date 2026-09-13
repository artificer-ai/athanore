/**
 * The header's filter strip: the status chips, the default that hides
 * finished runs, the widened `/`, and how the three compose (10
 * §Layout, D268).
 *
 * Only a browser runs a workflow to `completed` and watches the row go,
 * which is what the default is about; everything the chips do to a
 * fixed list is asserted in `src/components/RunList/__tests__`.
 */
import { expect, RUN_TIMEOUT, test } from './support/fixtures'

const STILL_GOING = 'still going'
const DONE_AND_GONE = 'done and gone'

test('the list hides finished runs until asked, and counts them anyway', async ({
  dashboard,
  server,
}) => {
  const page = dashboard.page
  await dashboard.open()

  // `plugged` first, because the pool is one worker deep and a `hold`
  // ahead of it would keep it `queued`; it finishes at once. The server
  // is asked whether it has, so that "no row" below means "hidden" and
  // not "not fetched yet".
  const doneId = await dashboard.submitOverApi('plugged', DONE_AND_GONE)
  await expect
    .poll(
      async () => {
        const response = await fetch(`${server.url}/api/runs/${doneId}`)
        return ((await response.json()) as { status: string }).status
      },
      { timeout: RUN_TIMEOUT },
    )
    .toBe('completed')
  await dashboard.submitOverApi('hold', STILL_GOING)

  // -- the default: the run still going is listed, the finished one is
  //    not, and the header counts both. `n runs` is the server's number;
  //    `n shown` is the filter's.
  await expect(dashboard.row(STILL_GOING)).toBeVisible()
  await expect(dashboard.row(DONE_AND_GONE)).toHaveCount(0)
  await expect(page.getByTestId('run-count')).toHaveText('2 runs')
  await expect(page.getByTestId('rows-shown')).toHaveText('1 shown')
  await expect(dashboard.statusChip('completed')).toHaveAttribute('aria-pressed', 'false')
  await expect(dashboard.statusChip('cancelled')).toHaveAttribute('aria-pressed', 'false')
  await expect(dashboard.statusChip('running')).toHaveAttribute('aria-pressed', 'true')

  // -- a filter that hides the selected run's row leaves the selection
  //    alone (10 §Layout, D204 (2)): `c` needs no confirmation (10
  //    §Keyboard), the run goes `cancelled`, the row goes with it, and
  //    `?run=` and the detail stay.
  await dashboard.select(STILL_GOING)
  const runId = new URL(page.url()).searchParams.get('run')
  expect(runId).not.toBeNull()
  await page.keyboard.press('c')
  await expect(dashboard.row(STILL_GOING)).toHaveCount(0, { timeout: RUN_TIMEOUT })
  expect(new URL(page.url()).searchParams.get('run')).toBe(runId)
  await expect(page.locator('[data-region="detail"]')).toBeVisible()
  await expect(page.getByTestId('selected-run')).toContainText(runId!.slice(0, 8))
  await expect(page.getByTestId('rows-shown')).toHaveText('0 shown')
  await expect(page.getByTestId('run-count')).toHaveText('2 runs')

  // -- one chip on brings its status back, and only its status.
  await dashboard.statusChip('cancelled').click()
  await expect(dashboard.status(STILL_GOING)).toHaveText('cancelled')
  await expect(dashboard.row(DONE_AND_GONE)).toHaveCount(0)
  await expect(page.getByTestId('rows-shown')).toHaveText('1 shown')

  // -- `all` turns every status on; the finished run is back, reading
  //    what it is. A status chip off again hides it again.
  await dashboard.showAllStatuses()
  await expect(dashboard.status(DONE_AND_GONE)).toHaveText('completed')
  await expect(page.getByTestId('rows-shown')).toHaveText('2 shown')
  await dashboard.statusChip('completed').click()
  await expect(dashboard.row(DONE_AND_GONE)).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'all statuses' })).toHaveAttribute(
    'aria-pressed',
    'false',
  )
  await dashboard.showAllStatuses()
  await expect(dashboard.row(DONE_AND_GONE)).toBeVisible()

  // -- the `/` input, with every status on: an id prefix, the workflow
  //    name and a title fragment each narrow the list, whatever their
  //    case; cleared, everything is back. Twelve characters of the id
  //    rather than the eight the RUN column shows, because two ULIDs
  //    minted within a quarter of a second share their first eight.
  const listed = () => expect.poll(() => dashboard.titles())
  await dashboard.filterInput().fill(doneId.slice(0, 12).toLowerCase())
  await listed().toEqual([DONE_AND_GONE])
  await dashboard.filterInput().fill('PLUGGED')
  await listed().toEqual([DONE_AND_GONE])
  await dashboard.filterInput().fill('hold')
  await listed().toEqual([STILL_GOING])
  await dashboard.filterInput().fill('going')
  await listed().toEqual([STILL_GOING])
  await dashboard.filterInput().fill('')
  await expect(dashboard.rows()).toHaveCount(2)

  // -- the kinds compose, AND across them: the workflow chip and a
  //    status that no run of it has is an empty list.
  await page.getByRole('radio', { name: 'plugged', exact: true }).click()
  await expect(dashboard.rows()).toHaveCount(1)
  await dashboard.statusChip('completed').click()
  await expect(dashboard.rows()).toHaveCount(0)
  await expect(page.getByTestId('rows-shown')).toHaveText('0 shown')
  await expect(page.getByTestId('run-count')).toHaveText('2 runs')
})

test('a submission from the overlay puts the filter back to its default', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  await dashboard.showAllStatuses()
  await dashboard.statusChip('queued').click()
  await expect(dashboard.statusChip('queued')).toHaveAttribute('aria-pressed', 'false')
  await dashboard.filterInput().fill('nothing matches this')

  // A run submitted under a filter that hides it would look like one
  // that was never queued at all (D268 (5)): the submission resets the
  // filter, and the row is what the operator sees.
  await dashboard.submit('hold', 'freshly queued')
  await expect(dashboard.filterInput()).toHaveValue('')
  await expect(dashboard.statusChip('queued')).toHaveAttribute('aria-pressed', 'true')
  await expect(dashboard.statusChip('completed')).toHaveAttribute('aria-pressed', 'false')
  await expect(page.getByRole('radio', { name: 'all', exact: true })).toHaveAttribute(
    'aria-checked',
    'true',
  )
})
