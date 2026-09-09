/**
 * The server-down banner, over a server that really goes away
 * (`docs/v1/17-serial-task-plan.md` § T068a, 10 §Realtime and caching).
 *
 * Two claims, and only a browser against a real process can check
 * either: that a tab whose event feed has stopped answering says so
 * without throwing away what it was showing, and that it comes back on
 * its own when the server does.
 *
 * Every wait here is on a state — the banner, the header's `data-down`,
 * the row that is still on screen — and never on a clock. The feed
 * reports `down` only after a retry has failed too (`sse.ts`), so how
 * long the banner takes is a function of the backoff and not something
 * a test may assume.
 */
import { expect, test } from './support/fixtures'

const TITLE = 'still on screen'

test('the banner appears when the server goes, and clears when it returns', async ({
  dashboard,
  server,
}) => {
  await dashboard.open()
  await dashboard.submitOverApi('hold', TITLE)
  await expect(dashboard.row(TITLE)).toBeVisible()

  await server.kill()

  const banner = dashboard.page.getByTestId('server-down-banner')
  await expect(banner).toBeVisible({ timeout: 30_000 })
  await expect(banner).toContainText('no server')
  await expect(banner.getByRole('button', { name: 'try now' })).toBeVisible()
  // The countdown is a state and not a clock: it says which of the two
  // things is true — an attempt is in flight, or one is due.
  await expect(banner.getByTestId('server-down-countdown')).toHaveText(
    /reconnecting…|retrying in \d+s/,
  )

  // "the last data stays visible": the strip is a strip and not an
  // overlay, and the counts grey out beside it rather than emptying.
  await expect(dashboard.row(TITLE)).toBeVisible()
  await expect(dashboard.page.getByTestId('header-counts')).toHaveAttribute(
    'data-down',
    'true',
  )
  await expect(dashboard.page.getByTestId('run-count')).toHaveText('1 runs')

  // The same port, so the tab is looking at the origin it was loaded
  // from; the feed's restart check notices the new process and refetches
  // the manifest (`sse.ts`).
  await server.start()

  await expect(banner).toBeHidden({ timeout: 60_000 })
  await expect(dashboard.page.getByTestId('header-counts')).toHaveAttribute(
    'data-down',
    'false',
  )
  await expect(dashboard.row(TITLE)).toBeVisible()

  // And the tab is live again: a run submitted after the restart
  // arrives on the reconnected feed.
  await dashboard.submitOverApi('hold', 'after the restart')
  await expect(dashboard.row('after the restart')).toBeVisible()
})
