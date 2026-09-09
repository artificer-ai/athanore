/**
 * A run, from the New Run overlay to `completed`, with a person in the
 * middle of it twice (`docs/v1/17-serial-task-plan.md` § T068a).
 *
 * This is the spec the rest of the suite is scaffolding for: the SPA,
 * the API, the engine and an ACP agent in one browser tab. The agent is
 * `FakeACPAgent` and the script it runs is `e2e/scenarios/probe.draft.json`
 * — it asks to write a file, which reaches the operator as a permission
 * request because `Builder`'s policy is `ask` (05 §Policies) — and the
 * node after it asks the operator where the work goes (04 §Waiting).
 * Nothing here is mocked in the browser.
 */
import { expect, test } from './support/fixtures'

const TITLE = 'ship the release notes'

test('submit, watch the graph, answer both questions, complete', async ({
  dashboard,
}) => {
  await dashboard.open()
  await dashboard.submit('probe', TITLE)
  await dashboard.select(TITLE)

  // 1. the graph shows progress: the start node is the one in flight.
  await dashboard.pane('graph')
  await expect(dashboard.graphRow('draft')).toHaveAttribute(
    'data-state',
    'in_progress',
  )
  await expect(dashboard.graphRow('ship')).toHaveAttribute('data-state', 'idle')

  // 2. the permission the agent asked for, answered `allow_once` — by
  //    the option id the server offered, never by position (D10).
  await dashboard.pane('requests')
  const permission = dashboard.openRequest('permission')
  await expect(permission).toBeVisible()
  await expect(permission.getByTestId('request-prompt')).toHaveText(
    'permission: write docs/release-notes.md',
  )
  await expect(permission.getByTestId('request-tool-heading')).toContainText('execute')
  const allowed = await dashboard.answer(permission, 'allow')
  await expect(allowed.getByTestId('request-author')).toHaveText('user')

  // 3. the node after it asks the operator a question of its own.
  const question = dashboard.openRequest('question')
  await expect(question).toBeVisible()
  await expect(question.getByTestId('request-prompt')).toHaveText('Ship it?')
  await dashboard.answer(question, 'ship')

  // 4. the run ends, and the graph says so.
  await expect(dashboard.status(TITLE)).toHaveText('completed')
  await dashboard.pane('graph')
  for (const node of ['draft', 'check', 'ship']) {
    await expect(dashboard.graphRow(node)).toHaveAttribute('data-state', 'done')
  }
  await expect(dashboard.graphRow('shelve')).toHaveAttribute('data-state', 'idle')
})

test('the panes carry the agent: the dock, the transcript, the work log', async ({
  dashboard,
}) => {
  const title = 'read the transcript'
  await dashboard.open()
  await dashboard.submit('probe', title)
  await dashboard.select(title)

  // 10 §Panes item 3: the request panel docks under the stream, and
  // "this is where permissions get answered". It is the same card the
  // requests pane draws, narrowed to the attempt on screen.
  await dashboard.pane('agent')
  const dock = dashboard.page.getByTestId('stream-request-dock')
  await expect(dock).toBeVisible()
  await dashboard.answer(dock.getByTestId('request-card'), 'allow')

  // The node after it asks its own question, and the dock follows the
  // attempt that is in flight rather than the one that has ended.
  await dashboard.answer(dock.getByTestId('request-card'), 'ship')
  await expect(dashboard.status(title)).toHaveText('completed')

  // An attempt that has ended is reached through the drawer: the
  // overview's NODES row opens it, and `focus stream` hands `?task=`
  // over to the agent pane (T063c).
  await dashboard.pane('overview')
  await dashboard.page.locator('[data-testid="node-rows"] [data-node="draft"]').click()
  await dashboard.page.getByTestId('task-focus-stream').click()
  const transcript = dashboard.page.getByTestId('stream-scroller')
  await expect(transcript).toContainText('The brief names one file')
  await expect(transcript).toContainText('Read the brief and the file it names.')
  await expect(dashboard.page.getByTestId('stream-task')).toContainText(
    'task 1 · draft',
  )

  // The scenario's `log` line is a POST the fake made against its own
  // task URL with its own task token (13 §Fakes), so it is in the log.
  await dashboard.pane('log')
  await expect(dashboard.page.getByTestId('log-scroller')).toContainText(
    'draft: rewrote the release notes',
  )
})
