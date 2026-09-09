/**
 * A plugin's own web component, mounted in the operator's browser
 * (`docs/v1/17-serial-task-plan.md` § T071, 09 §Escape hatch).
 *
 * `plugged` (`./workflows.py`) is a workflow that ships one ES module
 * and declares a `custom` pane for the tag that module defines. Nothing
 * in the SPA has ever heard of `<e2e-playfield>`: the pane exists
 * because the manifest lists it, the script loads because the manifest
 * lists its URL, and the element does its work through the three
 * capabilities of `window.athanore` and nothing else.
 *
 * That is why this spec is a browser spec rather than a vitest one.
 * jsdom loads no external resource and executes no injected module, so
 * "the SPA injects the asset" is the most a unit test can assert; here
 * the module actually runs, defines a custom element, fetches through
 * the host's `fetch`, and receives an event through the host's
 * `subscribe`.
 */
import { expect, test } from './support/fixtures'

const TITLE = 'mount the playfield'

/** What `plugged`'s route answers with (`./workflows.py`). */
const WORD = 'athanor'

test('a plugin element mounts, fetches, and is fed the event stream', async ({
  dashboard,
  page,
}) => {
  await dashboard.open()
  const runId = await dashboard.submitOverApi('plugged', TITLE)
  await dashboard.select(TITLE)

  // 1. the pane is in the cycle because the manifest put it there: a
  //    dot labelled by the panel's name, on the run of its own workflow.
  await dashboard.showPane('Playfield', 'plugged')

  // 2. the asset the manifest listed was injected, once, as a module.
  const scripts = page.locator(
    'script[data-athanore-asset="/plugins/plugged/static/playfield.js"]',
  )
  await expect(scripts).toHaveCount(1)
  await expect(scripts).toHaveAttribute('type', 'module')

  // 3. the tag mounted, with the scope on it (09 §Escape hatch).
  const element = page.getByTestId('plugin-element')
  await expect(element).toHaveAttribute('run-id', runId)
  await expect(element).toHaveAttribute('data-element', 'e2e-playfield')

  // 4. `window.athanore.fetch('/state?run_id=…')` reached the
  //    workflow's own route, under its own prefix and with the
  //    operator's credential: the word is the route's answer.
  await expect(page.getByTestId('playfield-word')).toHaveText(WORD)
  await expect(page.getByTestId('playfield-run')).toHaveText(runId)

  // 5. `theme.tokens` reached it too, so it is drawn in the design
  //    system's accent rather than in a colour of its own.
  await expect(page.getByTestId('playfield-word')).toHaveCSS(
    'color',
    'rgb(210, 206, 253)',
  )

  // 6. `subscribe(['log.appended'], …)` is the tab's one SSE stream,
  //    filtered: an operator note appended over the API arrives at the
  //    element without it opening a connection of its own.
  await expect(page.getByTestId('playfield-events')).toHaveText('0')
  const appended = await fetch(`${dashboard.server.url}/api/runs/${runId}/log`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ text: 'a note for the playfield' }),
  })
  expect(appended.ok).toBe(true)
  await expect(page.getByTestId('playfield-events')).toHaveText('1')
})

test('the pane still works on every visit, not only the first', async ({
  dashboard,
  page,
}) => {
  // A custom element that is already defined runs `connectedCallback`
  // synchronously as it is inserted, so the second and later mounts in a
  // document are the ones that catch a host which hands over
  // `window.athanore` and the element's own bridge too late. Cycling
  // away and back is the ordinary way an operator uses the pane bar.
  await dashboard.open()
  const runId = await dashboard.submitOverApi('plugged', TITLE)
  await dashboard.select(TITLE)

  for (const lap of [1, 2, 3]) {
    await dashboard.showPane('Playfield', 'plugged')
    // The tag is undefined on the first lap and defined on the others;
    // the element has to fetch through the bridge on all three.
    await expect(page.getByTestId('playfield-word'), `lap ${String(lap)}`).toHaveText(
      WORD,
    )
    // And be drawn: the host inserts the element into a `display:
    // contents` wrapper, so the pane lays it out the same way on every
    // lap as it did when React rendered the tag itself.
    await expect(page.getByTestId('plugin-element'), `lap ${String(lap)}`).toBeVisible()
    await expect(page.getByTestId('playfield-word'), `lap ${String(lap)}`).toHaveCSS(
      'color',
      'rgb(210, 206, 253)',
    )
    await expect(page.getByTestId('playfield-run'), `lap ${String(lap)}`).toHaveText(
      runId,
    )
    await dashboard.pane('log')
  }

  // Still one script: the remounts reused the module they injected.
  await expect(
    page.locator('script[data-athanore-asset="/plugins/plugged/static/playfield.js"]'),
  ).toHaveCount(1)
})

test('a traversal out of the asset directory is a 404, not a file', async ({
  dashboard,
}) => {
  // 12 §Plugins: assets are served by `StaticFiles`, so `../` reaches
  // nothing. Asserted here as well as in `tests/plugins/test_assets.py`
  // because this is the real server, over a real socket, with no test
  // client normalising the path on the way.
  const response = await fetch(
    `${dashboard.server.url}/plugins/plugged/static/%2e%2e/%2e%2e/athanore.db`,
  )

  expect(response.status).toBe(404)
  expect((await response.json()).code).toBe('not_found')
})
