/**
 * Live registration, followed by the dashboard
 * (`docs/v1/17-serial-task-plan.md` § T087, 22 §SPA, §Testing).
 *
 * A workflow the server never heard of at boot is written to a file,
 * `POST`ed, run, edited, `PUT`, run again, `DELETE`d while a run is in a
 * node, and `POST`ed back — and the page is never reloaded. What is
 * asserted is the dashboard following each step through the one event
 * stream: the library's list and viewer, the new-run chips, the graph
 * pane's rows, the run row's `⊘`, the pane cycle. The API is the hand
 * that registers, because the SPA has no control for it (22 §Scope);
 * the SPA is what is watched.
 *
 * The second test is the one thing the page cannot follow: a plugin's
 * JavaScript reloaded with different bytes. The manifest lists the same
 * file at a new `?v=`, a module the page already ran cannot run again,
 * and the honest thing is a banner and a reload (D225).
 *
 * The two surfaces this task adds — the row's `⊘` and the banner — are
 * put through the axe gate of `a11y.spec.ts` in the state that shows
 * them, because a marker only a sighted operator can read would be
 * half a marker (10 §Accessibility and quality).
 *
 * The workflow is `tempo`, and its stall is a file the spec controls
 * rather than a fake-agent scenario: recovery does not bump `attempt`,
 * so a scenario that slept would sleep again after the `POST` back and
 * the run could never finish. Removing a file the node polls makes "the
 * attempt stopped" and "the run resumed" two observations of one node
 * (D253).
 */
import { existsSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import AxeBuilder from '@axe-core/playwright'
import type { Page } from '@playwright/test'

import { A11Y_SCORE, axeScore, blocking, violationReport } from './support/a11y'
import { RUN_TIMEOUT, expect, test } from './support/fixtures'
import type { AthanoreServer } from './support/server'

/** The workflow every version of the file defines. */
const WORKFLOW = 'tempo'

/**
 * The file's stem. Not a stdlib name: a file target is executed into
 * `sys.modules` under it (22 §Reloading a module), and `tempo` alone
 * would be one import away from shadowing something.
 */
const MODULE = 'tempo_wf.py'

/** The gate `linger` polls: present, the node waits; absent, it returns. */
const HOLD = 'hold'

/** The prefix the manifest lists `tempo`'s one asset under (22 §Live mounting). */
const ASSET_PREFIX = `/plugins/${WORKFLOW}/static/tempo.js`

/** One call on the workflows API, as an operator's script would make it. */
async function api(
  server: AthanoreServer,
  method: 'GET' | 'POST' | 'PUT' | 'DELETE',
  path: string,
  body?: unknown,
): Promise<{ status: number; json: unknown }> {
  const response = await fetch(`${server.url}${path}`, {
    method,
    headers: { 'content-type': 'application/json' },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  return { status: response.status, json: await response.json() }
}

/**
 * The axe gate of `a11y.spec.ts`, over the page as it stands.
 *
 * Under `prefers-reduced-motion`: the `⊘` is only ever beside a pill
 * that reads `running`, and a `running` pill pulses (10 §Status
 * colours) — axe samples the animation wherever it is and reads a
 * quarter-opacity keyframe as a contrast failure of the pill, which is
 * the design's and not this task's. The design already answers that
 * media query by stopping the pulse (`theme.css`), and it is the state
 * an operator who needs the contrast is in.
 */
async function expectAccessible(page: Page): Promise<void> {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  try {
    const results = await new AxeBuilder({ page }).analyze()
    expect(blocking(results), violationReport(results)).toEqual([])
    expect(axeScore(results), violationReport(results)).toBeGreaterThanOrEqual(
      A11Y_SCORE,
    )
  } finally {
    await page.emulateMedia({ reducedMotion: null })
  }
}

/** Write the workflow's module into the scratch directory and name its target. */
function writeWorkflow(scratch: string, source: string): string {
  const file = join(scratch, MODULE)
  writeFileSync(file, source)
  return `${file}:wf`
}

/**
 * The workflow with a gated middle: an agent node, a node that waits
 * while the hold file exists, and a terminal node called `last`.
 *
 * `Builder` declares no `command`: `ATHANORE_AGENT_COMMAND` puts the
 * fake behind it (`support/server.ts`), and the fake's `default.json`
 * is a text turn that ends, so `draft` completes on its own.
 */
function gated(scratch: string, last: string): string {
  return `
import asyncio
from pathlib import Path

from athanore import ACPAgent, Workflow

HOLD = Path(${JSON.stringify(join(scratch, HOLD))})


class Builder(ACPAgent):
    pass


wf = Workflow(${JSON.stringify(WORKFLOW)})


@wf.node(start=True)
async def draft(linger):
    await Builder().run()
    return linger


@wf.node()
async def linger(${last}):
    while HOLD.exists():
        await asyncio.sleep(0.1)
    return ${last}


@wf.node()
async def ${last}():
    return "done"
`
}

/**
 * The workflow with a custom panel: one node that returns at once, and a
 * pane for the element `static/tempo.js` defines.
 */
function plugged(): string {
  return `
from athanore import Workflow

wf = Workflow(${JSON.stringify(WORKFLOW)}, assets="./static")


@wf.node(start=True)
async def play():
    return "played"


wf.panel("Tempo", slot="run", kind="custom", element="e2e-tempo")
`
}

/** `<e2e-tempo>`: one paragraph, reading `word`. */
function element(word: string): string {
  return `
class Tempo extends HTMLElement {
  connectedCallback() {
    const line = document.createElement('p')
    line.dataset.testid = 'tempo-word'
    line.textContent = ${JSON.stringify(word)}
    this.replaceChildren(line)
  }
}

customElements.define('e2e-tempo', Tempo)
`
}

test('a workflow added, reloaded, removed and added back is followed live', async ({
  dashboard,
  server,
  scratch,
}) => {
  await dashboard.open()

  // 1. add. The file exists, the server is told, and the page — never
  //    reloaded — lists it, offers it, and runs it.
  const target = writeWorkflow(scratch, gated(scratch, 'finish'))
  const added = await api(server, 'POST', '/api/workflows', { target })
  expect(added.status).toBe(201)

  await dashboard.openLibrary()
  await expect(dashboard.libraryRow(WORKFLOW)).toBeVisible()
  await dashboard.closeOverlay()

  await dashboard.submit(WORKFLOW, 'first light')
  // Watched to `completed`, which the list hides by default; after the
  // submission, which puts the filter back to that default (D268).
  await dashboard.showAllStatuses()
  await expect(dashboard.status('first light')).toHaveText('completed', {
    timeout: RUN_TIMEOUT,
  })
  await dashboard.select('first light')
  await dashboard.pane('graph')
  await expect(dashboard.graphRow('draft')).toBeVisible()
  await expect(dashboard.graphRow('linger')).toBeVisible()
  await expect(dashboard.graphRow('finish')).toBeVisible()

  // 2. reload. The terminal node is renamed; `PUT` with no target
  //    re-resolves the recorded one, which is `athanore workflows reload
  //    <name>`'s shape; the viewer and the next run's graph show the new
  //    node.
  writeWorkflow(scratch, gated(scratch, 'publish'))
  const reloaded = await api(server, 'PUT', `/api/workflows/${WORKFLOW}`, {})
  expect(reloaded.status).toBe(200)

  await dashboard.openLibrary()
  await dashboard.libraryRow(WORKFLOW).click()
  await expect(dashboard.librarySource()).toContainText('async def publish')
  await expect(dashboard.librarySource()).not.toContainText('async def finish')
  await dashboard.closeOverlay()

  await dashboard.submit(WORKFLOW, 'second light')
  await dashboard.showAllStatuses()
  await expect(dashboard.status('second light')).toHaveText('completed', {
    timeout: RUN_TIMEOUT,
  })
  await dashboard.select('second light')
  await dashboard.pane('graph')
  await expect(dashboard.graphRow('publish')).toBeVisible()
  await expect(dashboard.graphRow('finish')).toHaveCount(0)

  // 3. remove, mid-node. The hold file keeps `linger` polling; the
  //    removal interrupts exactly that attempt, and the run's row says
  //    the server no longer has its workflow while the run itself stays
  //    `running` (22 §Remove).
  writeFileSync(join(scratch, HOLD), '')
  const runId = await dashboard.submitOverApi(WORKFLOW, 'held light')
  await expect(dashboard.status('held light')).toHaveText('running', {
    timeout: RUN_TIMEOUT,
  })
  await expect(dashboard.row('held light')).toContainText('linger', {
    timeout: RUN_TIMEOUT,
  })

  const detail = await api(server, 'GET', `/api/runs/${runId}`)
  expect(detail.status).toBe(200)
  const inFlight = (detail.json as { tasks: { id: number; status: string }[] }).tasks.filter(
    (task) => task.status === 'in_progress',
  )
  expect(inFlight).toHaveLength(1)

  const removed = await api(server, 'DELETE', `/api/workflows/${WORKFLOW}`)
  expect(removed.status).toBe(200)
  // The wire's statement that the attempt was interrupted: the stats row
  // and the subprocess are the engine tests' business (22 §Testing).
  expect((removed.json as { task_ids: number[] }).task_ids).toEqual([inFlight[0]!.id])

  await expect(dashboard.unregistered('held light')).toBeVisible()
  await expect(dashboard.status('held light')).toHaveText('running')
  await expectAccessible(dashboard.page)

  await dashboard.openLibrary()
  await expect(dashboard.libraryRow(WORKFLOW)).toHaveCount(0)
  // The six the server booted with are untouched by it.
  await expect(dashboard.libraryRow('probe')).toBeVisible()
  await expect(dashboard.libraryRow('plugged')).toBeVisible()
  await dashboard.closeOverlay()

  await dashboard.openNewRun()
  await expect(dashboard.newRunChip('probe')).toBeVisible()
  await expect(dashboard.newRunChip(WORKFLOW)).toHaveCount(0)
  await dashboard.closeOverlay()

  // 4. add back. Recovery makes the interrupted row claimable again, and
  //    with the gate gone the node returns: the run finishes, and the
  //    `⊘` goes with the refetch that follows `workflow.registered`.
  rmSync(join(scratch, HOLD))
  const back = await api(server, 'POST', '/api/workflows', { target })
  expect(back.status).toBe(201)

  await expect(dashboard.unregistered('held light')).toHaveCount(0)
  await expect(dashboard.status('held light')).toHaveText('completed', {
    timeout: RUN_TIMEOUT,
  })
  await dashboard.openLibrary()
  await expect(dashboard.libraryRow(WORKFLOW)).toBeVisible()
})

test('a plugin whose JavaScript changed says so; nothing else does', async ({
  dashboard,
  page,
  server,
  scratch,
}) => {
  await dashboard.open()
  // `tempo` finishes as soon as its hold file is absent, and the list
  // hides a completed run by default (D268).
  await dashboard.showAllStatuses()

  // 1. a workflow with a custom pane, added live: its asset injects as
  //    any workflow's does, and the element draws.
  mkdirSync(join(scratch, 'static'))
  writeFileSync(join(scratch, 'static', 'tempo.js'), element('one'))
  const target = writeWorkflow(scratch, plugged())
  expect((await api(server, 'POST', '/api/workflows', { target })).status).toBe(201)

  await dashboard.submitOverApi(WORKFLOW, 'tempo one')
  await expect(dashboard.status('tempo one')).toHaveText('completed', {
    timeout: RUN_TIMEOUT,
  })
  await dashboard.select('tempo one')
  await dashboard.showPane('Tempo', WORKFLOW)
  await expect(page.getByTestId('tempo-word')).toHaveText('one')

  const scripts = page.locator(`script[data-athanore-asset^="${ASSET_PREFIX}"]`)
  await expect(scripts).toHaveCount(1)
  const firstUrl = await scripts.getAttribute('data-athanore-asset')
  expect(firstUrl).toContain('?v=')
  await expect(dashboard.pluginAssetsBanner()).toHaveCount(0)

  // 2. the file changes and the workflow is reloaded. The manifest now
  //    lists the same path at a new `?v=`; the page says so, injects
  //    nothing, and keeps drawing the element it has (22 §SPA, D225).
  writeFileSync(join(scratch, 'static', 'tempo.js'), element('two'))
  expect((await api(server, 'PUT', `/api/workflows/${WORKFLOW}`, {})).status).toBe(200)

  await expect(dashboard.pluginAssetsBanner()).toBeVisible()
  await expect(dashboard.pluginAssetsBanner()).toContainText(
    'plugin code changed — reload the page',
  )
  await expect(dashboard.pluginAssetsBanner()).toContainText(WORKFLOW)
  await expectAccessible(page)
  await expect(scripts).toHaveCount(1)
  await expect(scripts).toHaveAttribute('data-athanore-asset', firstUrl!)
  await expect(page.getByTestId('tempo-word')).toHaveText('one')
  // The manifest itself moved: the server is serving the new version.
  const manifest = (await api(server, 'GET', '/api/plugins')).json as {
    workflow: string
    assets?: string[]
  }[]
  const listed = manifest.find((entry) => entry.workflow === WORKFLOW)?.assets ?? []
  expect(listed).toHaveLength(1)
  expect(listed[0]).not.toBe(firstUrl)

  // 3. the banner's reload: a new document, with the new module in it.
  await dashboard.reloadFromBanner()
  await expect(dashboard.pluginAssetsBanner()).toHaveCount(0)
  // A new document starts the filter over at its default (D268): the
  // completed row is hidden again until the chip is pressed again.
  await dashboard.showAllStatuses()
  await dashboard.select('tempo one')
  await dashboard.showPane('Tempo', WORKFLOW)
  await expect(page.getByTestId('tempo-word')).toHaveText('two')
  await expect(scripts).toHaveCount(1)
  await expect(scripts).toHaveAttribute('data-athanore-asset', listed[0]!)

  // 4. removal: the pane leaves the cycle with its manifest entry, the
  //    index clamps onto a builtin, and nothing is stale — a removed
  //    workflow's script stays loaded and inert.
  expect((await api(server, 'DELETE', `/api/workflows/${WORKFLOW}`)).status).toBe(200)

  await expect(dashboard.paneDot('Tempo')).toHaveCount(0)
  await expect(page.getByTestId('pane-body')).toHaveAttribute('data-pane', /^_builtin:/)
  await expect(dashboard.pluginAssetsBanner()).toHaveCount(0)
  await expect(scripts).toHaveCount(1)
  expect(existsSync(join(scratch, MODULE))).toBe(true)
})
