/**
 * Nothing outside the ramp sets a size of its own
 * (`docs/v1/21-design-refresh.md` §Type scale, D195).
 *
 * `theme.test.ts` proves the six utilities of `theme.css` are exact
 * fractions of the base. That is only half of "the whole ramp
 * rescales": a component that writes an absolute `text-[…px]` class of
 * its own keeps that size at every step of the chooser, so at `xlarge`
 * a status word stays put inside a row that grew a quarter — the
 * mixed-scale text 21 §Type scale forbids. At the default base it looks
 * perfect, which is why nothing but a sweep finds it.
 *
 * A call site that needs a size the ramp has no rung for writes it in
 * the ramp's own form — `text-[calc(10.5rem/12)]`, the same pixels at
 * the default base and a fraction of it everywhere else — or earns a
 * seventh utility in `gen-theme.mjs`, which is a change to D150 and to
 * 10 §Type and density and so needs a decision row.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/**
 * The two ways to pin a font size past the ramp: a Tailwind arbitrary
 * value in pixels, `md:` and every other variant prefix included, and
 * an inline `style` in pixels. `rem`, `em` and `calc(…rem / 12)` are
 * all fractions of the base and so are all fine.
 *
 * The patterns are written to match no literal in this file, so the
 * sweep can cover itself along with everything else.
 */
const ABSOLUTE_SIZE = [/\btext-\[[\d.]+px\]/g, /\bfontSize:\s*['"`][\d.]+px/g]

/** Every TypeScript source of `web/src`, the tests included. */
function sources(): string[] {
  return readdirSync(SRC, { recursive: true, encoding: 'utf8' })
    .filter((path) => path.endsWith('.ts') || path.endsWith('.tsx'))
    .map((path) => join(SRC, path))
}

describe('the type ramp at its call sites', () => {
  it('sweeps the whole of src/', () => {
    // A sweep that resolved nothing would pass forever.
    const swept = sources()
    expect(swept.length).toBeGreaterThan(50)
    expect(swept.map((path) => relative(SRC, path))).toContain(
      join('components', 'RunList', 'StatusPill.tsx'),
    )
  })

  it('sets no absolute font size anywhere', () => {
    const offenders: string[] = []
    for (const path of sources()) {
      const source = readFileSync(path, 'utf8')
      for (const pattern of ABSOLUTE_SIZE) {
        for (const [match] of source.matchAll(pattern)) {
          offenders.push(`${relative(SRC, path)}: ${match}`)
        }
      }
    }
    expect(
      offenders,
      'these sizes do not move with the base the operator chose: write ' +
        'them as calc(<px>rem / 12), the ramp’s own form (21 §Type scale)',
    ).toEqual([])
  })
})
