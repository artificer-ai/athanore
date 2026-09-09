/**
 * The keyboard map, in a browser (`docs/v1/17-serial-task-plan.md` §
 * T068a, 10 §Keyboard).
 *
 * `src/keys/__tests__` already drives the table as a table; what only a
 * browser can say is that the keystrokes reach it — that `n` really
 * opens the overlay, that `esc` really closes it, that `b` really
 * collapses the list to its rail, and that `a` fires for the request
 * panel the keystroke came from and for nothing else (D51).
 */
import { expect, test } from './support/fixtures'

test('the map moves the selection, the panes and the overlays', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  await dashboard.submitOverApi('hold', 'alpha')
  await dashboard.submitOverApi('hold', 'beta')
  await expect(dashboard.rows()).toHaveCount(2)

  // `↑`/`↓` and `j`/`k` select, clamped: with nothing selected `↓` takes
  // the first row, and `k` at the top stays there.
  await page.keyboard.press('ArrowDown')
  await expect(dashboard.row('alpha')).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('j')
  await expect(dashboard.row('beta')).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('k')
  await expect(dashboard.row('alpha')).toHaveAttribute('aria-selected', 'true')
  await page.keyboard.press('k')
  await expect(dashboard.row('alpha')).toHaveAttribute('aria-selected', 'true')

  // `→` and `1` are the pane cycle; the label names the pane in view.
  const label = page.getByTestId('pane-label')
  await page.keyboard.press('1')
  await expect(label).toContainText('OVERVIEW')
  await page.keyboard.press('ArrowRight')
  await expect(label).not.toContainText('OVERVIEW')
  await page.keyboard.press('1')
  await expect(label).toContainText('OVERVIEW')

  // `n` opens the New Run overlay and `esc` closes it.
  await page.keyboard.press('n')
  await expect(page.getByTestId('new-run')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('new-run')).toBeHidden()

  // `?` is the footer chips, expanded (10 §Overlays).
  await page.keyboard.press('?')
  await expect(page.getByTestId('key-row').first()).toBeVisible()
  await expect(page.getByTestId('key-group').first()).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('key-row').first()).toBeHidden()

  // `b` collapses the run list to the rail `Splitter` draws in its place.
  await page.keyboard.press('b')
  await expect(page.getByTestId('runs-rail')).toBeVisible()
  await page.keyboard.press('b')
  await expect(page.getByTestId('runs-rail')).toBeHidden()

  // `^p` is a chord, so it fires wherever the caret is — including the
  // header's `/` box, which swallows every plain key.
  await page.getByRole('textbox', { name: 'filter runs' }).fill('alpha')
  await page.keyboard.press('n')
  await expect(page.getByTestId('new-run')).toBeHidden()
  await page.keyboard.press('Control+p')
  await expect(page.getByTestId('palette')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByTestId('palette')).toBeHidden()
})

test('`a` answers the request panel the keystroke came from', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  await dashboard.submit('probe', 'allow it with a key')
  await dashboard.select('allow it with a key')
  await dashboard.pane('requests')

  const permission = dashboard.openRequest('permission')
  await expect(permission).toBeVisible()
  const id = await permission.getAttribute('data-request')
  expect(id).not.toBeNull()

  // The caret is on `Deny`, and `a` still allows: the key picks by ACP
  // kind, never by the option under the cursor or by position (D10).
  await permission.locator('[data-testid="request-option"][data-option="reject"]').focus()
  await page.keyboard.press('a')

  const answered = dashboard.request(id ?? '')
  await expect(answered).toHaveAttribute('data-state', 'answered')
  await expect(answered.getByTestId('request-value')).toContainText('Allow Once')
})
