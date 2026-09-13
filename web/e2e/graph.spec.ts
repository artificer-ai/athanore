/**
 * The graph pane at the widths between a phone and a full desktop window
 * (`docs/v1/10-frontend.md` §Graph pane, D206 (10)).
 *
 * The canvas and the EDGES block sit side by side when there is room for
 * both and stack when there is not, and the decision is made on the
 * width of the *pane*. That is not the same number as the width of the
 * window: the run list, the splitter and the pane cycle all take width
 * off it, so a 900 px window leaves the pane around 460 px — less than
 * half of what the two columns need, and under the CSS breakpoint's
 * reading of the same moment ("768 px, so lay it out as a desktop") the
 * canvas was squeezed to a sliver with its cards clipped away and no
 * scroll and no gesture that reached them.
 *
 * So this sweeps the band: at every width from the breakpoint up to a
 * comfortable desktop the graph is drawn inside a canvas at least a card
 * wide, and at the top of the band the aside is beside it rather than
 * under it — the fix must not make the app stack forever.
 *
 * And the picture the canvas draws is **either legible or movable**. A
 * canvas of the right size can still fail an operator: fitting eight
 * ranks into a 320 px picture with no controls, no drag-pan and no
 * pinch puts a card at 69 × 19 px, where the name and the state glyph
 * cannot be read and nothing on screen recovers them. Zoom floor or
 * control strip — one of the two has to be there (D206 (11)).
 *
 * `ladder` is eight ranks, so neither a clipped canvas nor a thumbnail
 * can pass by accident.
 */
import type { Locator, Page } from '@playwright/test'

import { expect, RUN_TIMEOUT, test } from './support/fixtures'

const TITLE = 'a graph in a half-screen window'

/** A node card's width on the canvas (`panes/kinds/graph.ts`). */
const CARD_WIDTH = 208

/**
 * The band the pane has to keep working across, in a window 800 px tall.
 *
 * 768 is Tailwind's `md` — the width the app switches layouts at, and
 * the one the desktop project (1280) and the mobile project (390) leave
 * furthest untested. 1024 is an iPad in landscape and 1440 a laptop.
 */
const WIDTHS = [768, 900, 1024, 1440]

/** Half a pixel: the canvas draws through a fractional CSS transform. */
const SLACK = 0.5

/**
 * The zoom the pane's own `<Controls>` stop at, and the floor the fit
 * takes wherever those controls are drawn (`GraphCanvas.tsx`'s
 * `minZoom`). Under it the type inside a card is not type any more.
 */
const LEGIBLE_ZOOM = 0.4

/** The scale the canvas is currently drawing its contents at. */
async function zoomOf(page: Page): Promise<number> {
  return await page.evaluate(() => {
    const viewport = document.querySelector('.react-flow__viewport')
    if (viewport === null) return 0
    const transform = getComputedStyle(viewport).transform
    return transform === 'none' ? 1 : new DOMMatrixReadOnly(transform).a
  })
}

/**
 * What the operator has: a picture big enough to read, or a picture with
 * something to move it with. The zoom is in every answer so that a
 * failure names the number rather than the verdict.
 */
async function verdict(page: Page): Promise<string> {
  const zoom = await zoomOf(page)
  const at = `at zoom ${zoom.toFixed(3)}`
  if ((await page.getByTestId('rf__controls').count()) === 1) return `movable, ${at}`
  if (zoom >= LEGIBLE_ZOOM) return `legible, ${at}`
  return `a thumbnail ${at}, with nothing to zoom or pan it`
}

/** `stacked` or `split`, as the pane itself reports it. */
async function layoutOf(page: Page): Promise<string | null> {
  return await page.getByTestId('graph-frame').getAttribute('data-layout')
}

/** Which edges of `cards` fall outside `.react-flow`, named. */
async function clipped(page: Page, cards: [string, Locator][]): Promise<string[]> {
  const canvas = await page.locator('.react-flow').boundingBox()
  if (canvas === null) return ['the canvas has no box']
  const out: string[] = []
  for (const [which, card] of cards) {
    const box = await card.boundingBox()
    if (box === null) {
      out.push(`${which} has no box`)
      continue
    }
    if (box.y < canvas.y - SLACK) out.push(`${which} top`)
    if (box.y + box.height > canvas.y + canvas.height + SLACK) out.push(`${which} bottom`)
    if (box.x < canvas.x - SLACK) out.push(`${which} left`)
    if (box.x + box.width > canvas.x + canvas.width + SLACK) out.push(`${which} right`)
  }
  return out
}

test('the graph is drawn, and drawn usably, at every width from the breakpoint up', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await dashboard.open()
  // `ladder` waits on nothing and is complete at once, and the list hides
  // a completed run by default (D268): every status is turned on first,
  // and the run is submitted over the API, because a submission from the
  // overlay puts the filter back to its default and the row would be gone
  // before it could be clicked. The overlay is `run.spec.ts`'s subject.
  await dashboard.showAllStatuses()
  await dashboard.submitOverApi('ladder', TITLE)
  await dashboard.select(TITLE)
  await dashboard.pane('graph')

  const first = dashboard.graphRow('intake')
  const last = dashboard.graphRow('label')
  await expect(first).toBeVisible({ timeout: RUN_TIMEOUT })
  await expect(last).toBeVisible()

  for (const width of WIDTHS) {
    await page.setViewportSize({ width, height: 800 })

    // The defect this guards: the canvas kept its place in the layout
    // and lost its width, so the cards were in the DOM and nowhere on
    // screen. A canvas narrower than one card can draw no node.
    await expect
      .poll(async () => (await page.locator('.react-flow').boundingBox())?.width ?? 0, {
        message: `the canvas at ${String(width)} px`,
      })
      .toBeGreaterThanOrEqual(CARD_WIDTH)

    // And what it draws is worth drawing: either the type is legible or
    // the control strip is there to make it so. Asserting only that the
    // cards are inside the box passes a one-third-scale thumbnail.
    await expect
      .poll(async () => await verdict(page), {
        message: `the picture at ${String(width)} px`,
      })
      .toMatch(/^(movable|legible),/)

    // Split, the fit has the room it needs, so the whole graph is inside
    // the canvas with no panning at all.
    if ((await layoutOf(page)) === 'split') {
      await expect
        .poll(
          async () =>
            await clipped(page, [
              ['the first card', first],
              ['the last card', last],
            ]),
          { message: `clipped at ${String(width)} px` },
        )
        .toEqual([])
    }

    // The aside is always drawn, beside the canvas or under it.
    await expect(page.getByTestId('graph-legend-row').first()).toBeVisible()
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth - window.innerWidth,
      ),
      `horizontal scroll at ${String(width)} px`,
    ).toBeLessThanOrEqual(0)
  }
})

test('a pane with room for both columns still draws them side by side', async ({
  dashboard,
}) => {
  const page = dashboard.page
  await page.setViewportSize({ width: 1440, height: 900 })
  await dashboard.open()
  // As above: `ladder` is complete at once, and the row has to stay.
  await dashboard.showAllStatuses()
  await dashboard.submitOverApi('ladder', TITLE)
  await dashboard.select(TITLE)
  await dashboard.pane('graph')
  await expect(dashboard.graphRow('intake')).toBeVisible({ timeout: RUN_TIMEOUT })

  // 10 §Graph pane: the canvas fills the pane and the EDGES block scrolls
  // beside it. The stacking rule is a floor, not the layout.
  const canvas = await page.locator('.react-flow').boundingBox()
  const edges = await page.getByTestId('graph-legend-row').first().boundingBox()
  expect(canvas, 'the canvas has no box').not.toBeNull()
  expect(edges, 'the EDGES block has no box').not.toBeNull()
  if (canvas === null || edges === null) return
  expect(edges.x, 'EDGES sits to the right of the canvas').toBeGreaterThanOrEqual(
    canvas.x + canvas.width - SLACK,
  )

  // Which is the layout that keeps the zoom controls, because there is
  // something to pan (D206 (7)).
  await expect(page.getByTestId('rf__controls')).toHaveCount(1)
})
