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

  // The fanned node is drawn once, with a chip per branch: the wire's
  // edges name nodes, so a second card would leave every arrow into and
  // out of `build` ambiguous (D206 (2)). Each chip is keyed and titled
  // from the branch frame its attempts carry rather than from their
  // position (`panes/kinds/graph.ts`).
  await expect(dashboard.graphRow('build')).toHaveCount(1)
  const branches = dashboard.graphBranches('build')
  await expect(branches).toHaveCount(2)
  await expect(branches.nth(0)).toHaveAttribute('title', /branch 1 of 2 · alpha/)
  await expect(branches.nth(1)).toHaveAttribute('title', /branch 2 of 2 · beta/)
  await expect(branches.nth(0)).toHaveAttribute('data-branch', /:0$/)
  await expect(branches.nth(1)).toHaveAttribute('data-branch', /:1$/)

  // And each chip carries its own branch's state: `alpha` is through
  // while `beta` is still at the question, which is the fact the two
  // sub-lists of the rail proved and the chips prove on the card.
  await expect(branches.nth(0)).toHaveAttribute('data-state', 'done')
  await expect(branches.nth(1)).toHaveAttribute('data-state', 'waiting')

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
