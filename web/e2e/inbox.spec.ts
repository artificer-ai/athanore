/**
 * The inbox: what is waiting on the operator when no run is selected
 * (`docs/v1/17-serial-task-plan.md` § T068a, 06 §Surfaces, 10 §Panes
 * item 4).
 *
 * It is the one builtin pane that is not about the selected run —
 * `slot="global"` on the same `<ath-requests>` element the run's pane
 * uses — and the point of it is that an operator who opens the app to a
 * list of runs can see, and answer, what is waiting without picking one.
 */
import { expect, test } from './support/fixtures'

test('the inbox lists open requests across runs, and answers them', async ({
  dashboard,
}) => {
  await dashboard.open()
  // Submitting does not select: the New Run overlay leaves the operator
  // where they were (`overlays/NewRun.tsx`), which is this pane.
  await dashboard.submit('probe', 'nobody has selected me')
  await expect(dashboard.page.getByTestId('pane-inbox')).toBeVisible()

  const permission = dashboard.openRequest('permission')
  await expect(permission).toBeVisible()
  // The one list that spans runs is the one that says which run each
  // question came from (06 §SPA).
  await expect(permission.getByTestId('request-run')).toContainText('run ')
  await expect(dashboard.page.getByTestId('inbox-count')).toHaveText('⚠ 1 open')

  // Answerable in place, from here, with no run selected at all.
  await dashboard.answer(permission, 'allow')

  const question = dashboard.openRequest('question')
  await expect(question).toBeVisible()
  await expect(question.getByTestId('request-prompt')).toHaveText('Ship it?')
  await dashboard.answer(question, 'ship')

  await expect(dashboard.page.getByTestId('inbox-count')).toHaveText('○ none open')
  await expect(dashboard.page.getByText('nothing is waiting on you')).toBeVisible()
  await expect(dashboard.status('nobody has selected me')).toHaveText('completed')
})
