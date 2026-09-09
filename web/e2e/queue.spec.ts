/**
 * The dispatch list: `reorder`, `pause` and `resume`
 * (`docs/v1/17-serial-task-plan.md` § T068a, 04 §Operator operations).
 *
 * All three are about a run that is **not** running, so the suite needs
 * a queue — and a queue is what one worker and a run that does not
 * finish make. `hold`'s one node sleeps (`workflows.py`), the default
 * pool is one deep, and everything submitted behind it stays `queued`
 * with a place in the list that these operations move it around in.
 */
import { expect, test } from './support/fixtures'

test('the palette moves a queued run up the dispatch list', async ({ dashboard }) => {
  await dashboard.open()
  for (const title of ['first', 'second', 'third']) {
    await dashboard.submitOverApi('hold', title)
  }
  // `GET /api/runs` answers in `position` order, so the list *is* the
  // dispatch order (08 §Runs).
  await expect.poll(() => dashboard.titles()).toEqual(['first', 'second', 'third'])
  await expect(dashboard.status('first')).toHaveText('running')
  await expect(dashboard.status('third')).toHaveText('queued')

  await dashboard.select('third')
  await dashboard.command('move run up')

  await expect.poll(() => dashboard.titles()).toEqual(['first', 'third', 'second'])
  // The endpoint reports the place it settled on, and the toast is that
  // number rather than a sentence of our own (`overlays/runOps.ts`).
  await expect(dashboard.page.getByText(/^position \d+$/)).toBeVisible()
})

test('`p` pauses a queued run and resumes it', async ({ dashboard }) => {
  await dashboard.open()
  await dashboard.submitOverApi('hold', 'holds the worker')
  await dashboard.submitOverApi('hold', 'waits its turn')
  await expect(dashboard.status('waits its turn')).toHaveText('queued')

  await dashboard.select('waits its turn')
  await dashboard.page.keyboard.press('p')
  await expect(dashboard.status('waits its turn')).toHaveText('paused')

  // Resumed, it reads `running`: 04 §Operator operations puts a resumed
  // run there and keeps no record of what it was before it was paused,
  // so the pill says `running` while the attempt is still waiting for
  // the one worker the run in front is holding.
  await dashboard.page.keyboard.press('p')
  await expect(dashboard.status('waits its turn')).toHaveText('running')
})
