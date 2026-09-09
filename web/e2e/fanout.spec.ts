/**
 * A fan-out closed by a join, drawn as `k of n`
 * (`docs/v1/17-serial-task-plan.md` § T068a, 10 §Graph pane).
 *
 * `spread` opens two branches and one of them stops to ask the operator
 * a question (`workflows.py`), so the join sits with one arrival of two
 * for as long as the spec needs to read it. `arrivals` is on the wire
 * only while a fan-out into that node is still open
 * (`athanore/api/routers/runs.py`), which is exactly the fact the row is
 * reporting: it is the one thing an operator watching a fan-in is
 * waiting for, so it outranks everything else the column could say.
 */
import { expect, test } from './support/fixtures'

const TITLE = 'two branches'

test('a join with a fan-out still open reads `1 of 2 arrived`', async ({
  dashboard,
}) => {
  await dashboard.open()
  await dashboard.submit('spread', TITLE)
  await dashboard.select(TITLE)
  await dashboard.pane('graph')

  await expect(dashboard.graphDetail('release')).toHaveText('1 of 2 arrived')

  // Each branch is a sub-list of its own, labelled from the branch frame
  // its attempts carry rather than from their position (`panes/kinds/graph.ts`).
  const branches = dashboard.page.getByTestId('graph-branch-label')
  await expect(branches).toHaveCount(2)
  await expect(branches.nth(0)).toContainText('branch 1 of 2 · alpha')
  await expect(branches.nth(1)).toContainText('branch 2 of 2 · beta')

  // Answering the branch that stopped closes the fan-out: the join fires
  // and the column has nothing left to count.
  await dashboard.pane('requests')
  const question = dashboard.openRequest('question')
  await expect(question.getByTestId('request-prompt')).toHaveText('Approve beta?')
  await dashboard.answer(question, 'approve')

  await expect(dashboard.status(TITLE)).toHaveText('completed')
  await dashboard.pane('graph')
  await expect(dashboard.graphDetail('release')).not.toContainText('arrived')
})
