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
import { test as base, expect, type Locator, type Page } from '@playwright/test'

import { AthanoreServer } from './server'

/** The workflow name the builtin panels are declared under (09 §Builtins). */
const BUILTIN_WORKFLOW = '_builtin'

/** How long a run of the fixture workflows may take to reach a state. */
export const RUN_TIMEOUT = 30_000

/** The workflows `support/server.ts` registers (`../workflows.py`). */
export type FixtureWorkflow = 'probe' | 'spread' | 'hold' | 'plugged'

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

  /** Submit a run the way an operator does: the New Run overlay. */
  async submit(workflow: FixtureWorkflow, title: string): Promise<void> {
    await this.page.getByRole('button', { name: 'new run', exact: true }).click()
    const panel = this.page.getByTestId('new-run')
    await expect(panel).toBeVisible()
    await panel.getByRole('radio', { name: workflow, exact: true }).click()
    await panel.locator('#new-run-title').fill(title)
    await panel.getByRole('button', { name: 'submit run' }).click()
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
  async submitOverApi(workflow: FixtureWorkflow, title: string): Promise<string> {
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

  // -- the detail region -----------------------------------------------

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

  /** One row of the graph rail. */
  graphRow(node: string): Locator {
    return this.page.locator(`[data-testid="graph-row"][data-node="${node}"]`)
  }

  /** What a graph row says in its right-hand column (10 §Graph pane). */
  graphDetail(node: string): Locator {
    return this.graphRow(node).getByTestId('graph-detail')
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
  async answer(card: Locator, optionId: string): Promise<Locator> {
    const id = await card.getAttribute('data-request')
    if (id === null) throw new Error('that is not a request card')
    await card.locator(`[data-testid="request-option"][data-option="${optionId}"]`).click()
    await expect(
      this.page.locator(
        `[data-testid="request-card"][data-request="${id}"][data-state="pending"]`,
      ),
    ).toHaveCount(0, { timeout: RUN_TIMEOUT })
    return this.request(id)
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

export const test = base.extend<{ server: AthanoreServer; dashboard: Dashboard }>({
  server: async ({}, use) => {
    const server = new AthanoreServer()
    await server.start()
    try {
      await use(server)
    } finally {
      await server.stop()
    }
  },

  dashboard: async ({ page, server }, use) => {
    await use(new Dashboard(page, server))
  },
})

export { expect }
