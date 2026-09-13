/**
 * The `test` every spec in this suite imports: a server, a browser page
 * pointed at it, and the handful of gestures the dashboard is driven by.
 *
 * **One server per test.** Playwright's `webServer` would give the whole
 * run a single one, and two of these specs need a machine of their own —
 * the queue specs fill the one worker slot on purpose, and the
 * connection spec kills the process. A per-test fixture costs a second
 * of start-up and buys specs that can be read, and run, in any order.
 *
 * `Dashboard` is a page object and not a helper module: every locator in
 * the suite is here, so a `data-testid` that moves is one edit rather
 * than nine, and a spec reads as the operator's story rather than as
 * CSS.
 */
import { mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { test as base, expect, type Locator, type Page } from '@playwright/test'

import { AthanoreServer } from './server'

/** The workflow name the builtin panels are declared under (09 §Builtins). */
const BUILTIN_WORKFLOW = '_builtin'

/** How long a run of the fixture workflows may take to reach a state. */
export const RUN_TIMEOUT = 30_000

/**
 * The viewport the mobile gate is pinned to: one iPhone-class screen,
 * with `hasTouch` and `isMobile`, and every activation a `tap()` (D197,
 * `../mobile.spec.ts`).
 */
export const NARROW_VIEWPORT = { width: 390, height: 844 }

/**
 * The workflows `support/server.ts` registers (`../workflows.py`).
 *
 * What a spec may name without registering anything first. A spec that
 * registers a workflow of its own over the API (`../registration.spec.ts`)
 * submits it by name, so the gestures below take a `string`; the union
 * stays for what it documents.
 */
export type FixtureWorkflow =
  | 'probe'
  | 'spread'
  | 'hold'
  | 'flop'
  | 'ladder'
  | 'plugged'

/**
 * How a control is activated: with a mouse, or with a finger.
 *
 * The mobile spec passes `tap` everywhere, because a `click()` that
 * passes says nothing about whether a touch device can operate the app
 * (D197); every other spec takes the default.
 */
export type Gesture = 'click' | 'tap'

export class Dashboard {
  readonly page: Page
  readonly server: AthanoreServer

  constructor(page: Page, server: AthanoreServer) {
    this.page = page
    this.server = server
  }

  /** Load the SPA the server itself serves, and wait for its shell. */
  async open(): Promise<void> {
    await this.page.goto(this.server.url)
    await expect(this.page.getByRole('heading', { name: 'ATHANORE' })).toBeVisible()
    // The run list has answered: every spec's first act is to read or
    // click a row, and an empty list is a state this one shows.
    await expect(this.page.getByTestId('rows-shown')).toBeVisible()
  }

  // -- the run list ----------------------------------------------------

  /** Every run row, in the dispatch order the API sent (08 §Runs). */
  rows(): Locator {
    return this.page.locator('[data-region="list"] [role="option"]')
  }

  /** The row of the run with this title. */
  row(title: string): Locator {
    return this.rows().filter({ hasText: title })
  }

  /** The titles on screen, top to bottom. */
  async titles(): Promise<string[]> {
    return this.rows().evaluateAll((rows) =>
      rows.map((row) => (row.children[2]?.textContent ?? '').trim()),
    )
  }

  /** Click a row: the route writes `?run=` and the detail follows. */
  async select(title: string): Promise<void> {
    await this.row(title).click()
    await expect(this.row(title)).toHaveAttribute('aria-selected', 'true')
  }

  /**
   * Turn every status chip on: the header's `all statuses` (10 §Layout).
   *
   * The list hides finished runs by default (D268), and `status()` reads
   * the row. A spec that watches a run finish, or submits one that
   * finishes without a request in the way, turns the chip on first —
   * here and not in `open()`, so the default is still there for
   * `../filters.spec.ts` to test.
   */
  async showAllStatuses(by: Gesture = 'click'): Promise<void> {
    const chip = this.page
      .getByRole('banner')
      .getByRole('button', { name: 'all statuses' })
    if (by === 'tap') await chip.tap()
    else await chip.click()
    await expect(chip).toHaveAttribute('aria-pressed', 'true')
  }

  /** One status chip of the header's group, by the status word. */
  statusChip(status: string): Locator {
    return this.page
      .getByRole('toolbar', { name: 'filter by status' })
      .getByRole('button', { name: status, exact: true })
  }

  /** The header's `/` input. */
  filterInput(): Locator {
    return this.page.getByRole('textbox', { name: 'filter runs' })
  }

  /**
   * The status pill of a run's row (10 §Components).
   *
   * `data-tone` is the pill and nothing else in a row carries it; the
   * word inside it is the run's status, because colour is never the only
   * signal (10 §Accessibility and quality).
   */
  status(title: string): Locator {
    return this.row(title).locator('[data-tone]')
  }

  // -- submitting ------------------------------------------------------

  /**
   * Submit a run the way an operator does: the New Run overlay.
   *
   * The title is typed rather than activated whichever gesture is
   * asked for — an on-screen keyboard into a focused input is how a
   * phone types, and 21 §Touch operation says so in as many words.
   */
  async submit(workflow: string, title: string, by: Gesture = 'click'): Promise<void> {
    const act = async (target: Locator) => {
      if (by === 'tap') await target.tap()
      else await target.click()
    }
    await act(this.page.getByRole('button', { name: 'new run', exact: true }))
    const panel = this.page.getByTestId('new-run')
    await expect(panel).toBeVisible()
    await act(panel.getByRole('radio', { name: workflow, exact: true }))
    await panel.locator('#new-run-title').fill(title)
    await act(panel.getByRole('button', { name: 'submit run' }))
    await expect(panel).toBeHidden()
    await expect(this.row(title)).toBeVisible()
  }

  /**
   * Submit a run over the API.
   *
   * For the runs a spec needs *around* the one it is about — the two
   * that make a queue for `reorder` to move something in. The gesture
   * under test is always the browser's; this is the fixture.
   */
  async submitOverApi(workflow: string, title: string): Promise<string> {
    const response = await fetch(`${this.server.url}/api/workflows/${workflow}/runs`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ title, description: '' }),
    })
    if (!response.ok) {
      throw new Error(`submitting ${workflow} failed: ${String(response.status)}`)
    }
    const created = (await response.json()) as { run_id: string }
    return created.run_id
  }

  /**
   * The `⊘` on a run's row: this server has no workflow of that name
   * (22 §Remove, 10 §Attention).
   */
  unregistered(title: string): Locator {
    return this.row(title).getByTestId('run-unregistered')
  }

  // -- the detail region -----------------------------------------------

  /** One dot of the pane bar, by the pane's name. */
  paneDot(name: string): Locator {
    return this.page.locator(`[data-pane="${name}"][role="radio"]`)
  }

  /** Show a builtin pane by name: the bar's dots are a radio group. */
  async pane(name: string): Promise<void> {
    await this.showPane(name, BUILTIN_WORKFLOW)
  }

  /**
   * Show a pane a workflow contributed, by its name and its workflow.
   *
   * The same gesture as {@link Dashboard.pane} — a plugin's pane is a
   * dot in the same bar (09 §Builtins are plugins) — with the manifest
   * id it settles on named, because that id is `<workflow>:<panel>` and
   * a plugin's is not `_builtin`'s.
   */
  async showPane(name: string, workflow: string): Promise<void> {
    await this.page.locator(`[data-pane="${name}"][role="radio"]`).click()
    // The pane host names the panel it is drawing by its manifest id,
    // which is `<workflow>:<panel>` (09).
    await expect(this.page.getByTestId('pane-body')).toHaveAttribute(
      'data-pane',
      `${workflow}:${name}`,
    )
  }

  /** One node's card on the graph canvas. */
  graphRow(node: string): Locator {
    return this.page.locator(`[data-testid="graph-row"][data-node="${node}"]`)
  }

  /** What a node's card says on its detail line (10 §Graph pane). */
  graphDetail(node: string): Locator {
    return this.graphRow(node).getByTestId('graph-detail')
  }

  /**
   * The branch chips inside one node's card: one per branch of the
   * fan-out it ran in (10 §Graph pane, D206 (2)).
   *
   * A fan-out never draws a second card — the wire's edges name nodes —
   * so this is where a run's branches are visible on the canvas.
   */
  graphBranches(node: string): Locator {
    return this.graphRow(node).getByTestId('graph-branch')
  }

  // -- the overlays ----------------------------------------------------

  /**
   * Run one command from the palette, the way 10 §Overlays describes it:
   * `^p`, then the row.
   *
   * The row is clicked rather than typed-and-entered because the
   * catalogue is what is being exercised — `reorder` has no key of its
   * own (D175), and the palette is the whole of how an operator reaches
   * it.
   */
  async command(name: string): Promise<void> {
    await this.page.keyboard.press('Control+p')
    const palette = this.page.getByTestId('palette')
    await expect(palette).toBeVisible()
    await palette.locator(`[cmdk-item][data-value="${name}"]`).click()
    await expect(palette).toBeHidden()
  }

  /** Open the workflow library from the header's `workflows` button. */
  async openLibrary(): Promise<Locator> {
    await this.page.getByRole('button', { name: 'workflows', exact: true }).click()
    const library = this.page.getByTestId('library')
    await expect(library).toBeVisible()
    return library
  }

  /** The library's row for a workflow, by name (10 §Overlays). */
  libraryRow(name: string): Locator {
    return this.page.locator(`[data-testid="library-list"] [data-workflow="${name}"]`)
  }

  /** The library's source viewer: the selected workflow's Python. */
  librarySource(): Locator {
    return this.page.getByTestId('library-source')
  }

  /** Open the New Run overlay without submitting anything. */
  async openNewRun(): Promise<Locator> {
    await this.page.getByRole('button', { name: 'new run', exact: true }).click()
    const panel = this.page.getByTestId('new-run')
    await expect(panel).toBeVisible()
    return panel
  }

  /** The New Run overlay's chip for a workflow, by name. */
  newRunChip(name: string): Locator {
    return this.page.getByTestId('new-run').getByRole('radio', { name, exact: true })
  }

  /** `esc`: whichever overlay is up goes down (10 §Overlays). */
  async closeOverlay(): Promise<void> {
    await this.page.keyboard.press('Escape')
    await expect(this.page.getByTestId('library')).toHaveCount(0)
    await expect(this.page.getByTestId('new-run')).toHaveCount(0)
  }

  // -- the banners -----------------------------------------------------

  /**
   * The strip that says a plugin's JavaScript changed under this page
   * and only a reload can follow it (22 §SPA).
   */
  pluginAssetsBanner(): Locator {
    return this.page.getByTestId('plugin-assets-banner')
  }

  /** Press the banner's `reload`, and wait for the shell as `open` does. */
  async reloadFromBanner(): Promise<void> {
    await this.pluginAssetsBanner().getByRole('button', { name: 'reload' }).click()
    await expect(this.page.getByRole('heading', { name: 'ATHANORE' })).toBeVisible()
    await expect(this.page.getByTestId('rows-shown')).toBeVisible()
  }

  // -- requests --------------------------------------------------------

  /** Every request card on screen, in the pane that is showing them. */
  requests(): Locator {
    return this.page.getByTestId('request-card')
  }

  /** The one open request of this kind (06 §The model). */
  openRequest(kind: 'permission' | 'question'): Locator {
    return this.page.locator(
      `[data-testid="request-card"][data-kind="${kind}"][data-state="pending"]`,
    )
  }

  /** One request card by id, in whatever state it is now in. */
  request(id: string): Locator {
    return this.page.locator(`[data-testid="request-card"][data-request="${id}"]`)
  }

  /**
   * Answer an `options` request by the option id the server offered —
   * never by position, which is the bug D10 exists for — and return the
   * card once the server has recorded it.
   *
   * What is waited for is that the question is no longer open — the one
   * thing both surfaces that draw it agree on. The requests pane keeps
   * an answered request as history and the agent pane's dock carries
   * only the open ones (10 §Panes item 3), so "the card now reads
   * answered" is true in one place and "the card has gone" in the other.
   *
   * The card that comes back is scoped by request id rather than by
   * state, because the locator a spec found a *pending* request with
   * stops matching the moment it is answered.
   */
  async answer(
    card: Locator,
    optionId: string,
    by: Gesture = 'click',
  ): Promise<Locator> {
    const id = await card.getAttribute('data-request')
    if (id === null) throw new Error('that is not a request card')
    const option = card.locator(
      `[data-testid="request-option"][data-option="${optionId}"]`,
    )
    if (by === 'tap') await option.tap()
    else await option.click()
    await expect(
      this.page.locator(
        `[data-testid="request-card"][data-request="${id}"][data-state="pending"]`,
      ),
    ).toHaveCount(0, { timeout: RUN_TIMEOUT })
    return this.request(id)
  }

  // -- narrow chrome ---------------------------------------------------

  /**
   * Open the palette the way a phone does: the footer button, tapped.
   *
   * `^p` is the desktop route and stays bound at every width; the button
   * is the one 21 §Narrow layout leaves in the footer, and the palette
   * behind it is the touch route to every operator action (D176).
   */
  async tapPalette(): Promise<Locator> {
    await this.page.getByRole('button', { name: 'palette' }).tap()
    const palette = this.page.getByTestId('palette')
    await expect(palette).toBeVisible()
    return palette
  }

  /** Run one palette command by touch: the button, then the row. */
  async tapCommand(name: string): Promise<void> {
    const palette = await this.tapPalette()
    await palette.locator(`[cmdk-item][data-value="${name}"]`).tap()
    await expect(palette).toBeHidden()
  }

  /**
   * The pane bar's back control, below the breakpoint (21 §Narrow): the
   * detail's `←`, and the global screen's — both go to the list (D218).
   */
  back(): Locator {
    return this.page.getByRole('button', { name: 'back to runs' })
  }

  /**
   * The footer's `global panes` toggle: the discoverable route to the
   * narrow global screen (21 §Regions, narrow, D216).
   */
  globalPanes(): Locator {
    return this.page.getByRole('button', { name: 'global panes' })
  }


  /**
   * A horizontal swipe across the middle of the screen, as a finger
   * makes one: through CDP's touch pipeline, not a synthetic
   * `TouchEvent`.
   *
   * D197's reason applies to a gesture as it does to a tap: a
   * `dispatchEvent` from inside the page would prove the handler and
   * nothing about the browser's touch pipeline. The suite is Chromium
   * only (`playwright.config.ts`), so CDP is available to every test.
   * Both ends sit inside the 24 px edges the recogniser leaves to the
   * browser's own back gesture, with 200 px of travel between them
   * (`src/lib/useSwipe.ts`); `startX` is for the one test that wants to
   * start *in* the edge and see nothing happen.
   */
  async swipe(
    direction: 'left' | 'right',
    startX?: number,
  ): Promise<void> {
    const y = 500
    const x0 = startX ?? (direction === 'right' ? 100 : 300)
    const x1 = x0 + (direction === 'right' ? 200 : -200)
    const cdp = await this.page.context().newCDPSession(this.page)
    try {
      await cdp.send('Input.dispatchTouchEvent', {
        type: 'touchStart',
        touchPoints: [{ x: x0, y }],
      })
      const steps = 4
      for (let i = 1; i <= steps; i += 1) {
        await cdp.send('Input.dispatchTouchEvent', {
          type: 'touchMove',
          touchPoints: [{ x: x0 + ((x1 - x0) * i) / steps, y }],
        })
      }
      await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] })
    } finally {
      await cdp.detach()
    }
  }

  /** The pane bar's `▶`: the touch route through the pane cycle. */
  nextPane(): Locator {
    return this.page.getByRole('button', { name: 'next pane' })
  }

  /** What the pane bar says the current pane is, `NAME (i/n)`. */
  paneLabel(): Locator {
    return this.page.getByTestId('pane-label')
  }

  /** The close affordance every overlay's header carries when narrow. */
  overlayClose(panel: Locator): Locator {
    return panel.getByRole('button', { name: 'close' })
  }

  // -- the type scale --------------------------------------------------

  /**
   * Choose a step of the type ramp from the header's chooser, by mouse
   * (21 §Type scale, D196).
   *
   * The gesture is the operator's whole one: the icon-only button, then
   * the row in the popover. What it settles on is `data-font-size` on
   * `<html>` — absent for `default`, which is the design's own base.
   */
  async chooseFontSize(step: 'small' | 'default' | 'large' | 'xlarge'): Promise<void> {
    await this.page.getByRole('button', { name: 'text size' }).click()
    await this.page.getByRole('radio', { name: step, exact: true }).click()
    await this.page.keyboard.press('Escape')
    await expect(this.page.getByRole('radiogroup', { name: 'text size' })).toHaveCount(0)
    if (step === 'default') {
      await expect(this.page.locator('html')).not.toHaveAttribute('data-font-size', /./)
    } else {
      await expect(this.page.locator('html')).toHaveAttribute('data-font-size', step)
    }
  }

  /** The rendered `font-size` of an element, in pixels. */
  async fontSize(locator: Locator): Promise<number> {
    return locator.evaluate(
      (element) => Number.parseFloat(getComputedStyle(element).fontSize),
    )
  }
}

export const test = base.extend<{
  server: AthanoreServer
  dashboard: Dashboard
  scratch: string
}>({
  server: async ({}, use) => {
    const server = new AthanoreServer()
    await server.start()
    try {
      await use(server)
    } finally {
      await server.stop()
    }
  },

  /**
   * A directory of the test's own, outside the server's root, for the
   * workflow files a spec writes and registers (`../registration.spec.ts`).
   * Gone when the test is.
   */
  scratch: async ({}, use) => {
    const directory = mkdtempSync(join(tmpdir(), 'athanore-e2e-scratch-'))
    try {
      await use(directory)
    } finally {
      rmSync(directory, { recursive: true, force: true })
    }
  },

  dashboard: async ({ page, server }, use) => {
    await use(new Dashboard(page, server))
  },
})

export { expect }
