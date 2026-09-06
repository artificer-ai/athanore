/**
 * theme.css is generated from docs/v1/design/nocturne.css and never
 * hand-edited (AGENTS.md §Conventions). These tests are what makes that
 * true: they run in `pnpm test`, which is a step of `./scripts/test.sh`
 * and of CI's `web` job, so an edit to either file that was not followed
 * by `pnpm gen:theme` turns the gate red.
 */
import { spawnSync } from 'node:child_process'
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '../..')
const GENERATOR = resolve(WEB, 'scripts/gen-theme.mjs')
const SOURCE = resolve(WEB, '../docs/v1/design/nocturne.css')
const THEME = resolve(WEB, 'src/styles/theme.css')

const nocturne = readFileSync(SOURCE, 'utf8')
const theme = readFileSync(THEME, 'utf8')

/** Every `--name: value;` Nocturne declares inside a `:root` block. */
function nocturneTokens(): [string, string][] {
  const declarations: [string, string][] = []
  for (const line of nocturne.split('\n')) {
    const match = /^\s*(--[a-z0-9-]+)\s*:\s*([^;]+?)\s*;/i.exec(line)
    if (match?.[1] && match[2]) declarations.push([match[1], match[2]])
  }
  return declarations
}

describe('theme.css', () => {
  it('is what gen-theme.mjs builds from nocturne.css', () => {
    const check = spawnSync(process.execPath, [GENERATOR, '--check'], {
      encoding: 'utf8',
    })
    expect(check.error).toBeUndefined()
    expect(`${check.stdout}${check.stderr}`.trim()).toBe('')
    expect(check.status).toBe(0)
  })

  it('carries every --color-, --space-, --shadow- and --ath- token', () => {
    const copied = nocturneTokens().filter(([name]) =>
      ['--color-', '--space-', '--shadow-', '--ath-'].some((p) => name.startsWith(p)),
    )
    expect(copied.length).toBeGreaterThan(40)
    for (const [name, value] of copied) {
      expect(theme, `${name} is missing or changed`).toContain(`${name}: ${value};`)
    }
  })

  it('does not copy the token families the app does not use', () => {
    // --radius-* and --font-heading/--font-body are Nocturne's document
    // defaults for a document, not for a terminal. The app declares its
    // own radius and its one mono face further down the file instead
    // (10 §Design system, D71), so Nocturne's values must not appear.
    for (const [name, value] of nocturneTokens()) {
      const copied = ['--color-', '--space-', '--shadow-', '--ath-'].some((p) =>
        name.startsWith(p),
      )
      if (!copied) {
        expect(theme, `${name} should not have been copied`).not.toContain(
          `${name}: ${value};`,
        )
      }
    }
  })

  it('maps every shadcn variable of 10 §Tokens → shadcn', () => {
    const mapping: [string, string][] = [
      ['--background', 'var(--color-bg)'],
      ['--card', 'var(--color-surface)'],
      ['--popover', 'var(--color-surface)'],
      ['--secondary', 'var(--color-surface)'],
      ['--foreground', 'var(--color-text)'],
      ['--muted-foreground', 'var(--color-neutral-500)'],
      ['--muted', 'var(--color-neutral-900)'],
      ['--border', 'var(--color-neutral-800)'],
      ['--input', 'var(--color-neutral-800)'],
      ['--primary', 'var(--color-accent)'],
      ['--primary-foreground', 'var(--color-accent-200)'],
      ['--accent', 'color-mix(in srgb, var(--color-accent) 16%, transparent)'],
      ['--destructive', 'var(--ath-status-fail)'],
      ['--ring', 'var(--color-accent)'],
      ['--chart-1', 'var(--color-accent)'],
      ['--chart-2', 'var(--color-accent-700)'],
      ['--chart-3', 'var(--color-accent-2-400)'],
    ]
    for (const [name, value] of mapping) {
      expect(theme, `${name} is not mapped onto ${value}`).toContain(
        `${name}: ${value};`,
      )
    }
  })

  it("leaves the radius at Nocturne's 8 px (D71)", () => {
    expect(theme).toContain('--radius: 8px;')
    expect(theme).not.toContain('--radius: var(--ath-radius)')
  })

  it('exposes the shadcn variables to Tailwind and no undefined ones', () => {
    const inline = /@theme inline \{([\s\S]*?)\n\}/.exec(theme)?.[1]
    expect(inline).toBeDefined()
    expect(inline).toContain('--color-background: var(--background);')
    expect(inline).toContain("--font-mono: 'JetBrains Mono Variable', var(--ath-font-mono);")
    // Roles 10 does not define would resolve to nothing at runtime.
    expect(inline).not.toContain('--color-sidebar')
    expect(inline).not.toContain('--color-chart-4')
    expect(inline).not.toContain('--color-chart-5')
  })

  it('sets the 12 px base of the app type scale', () => {
    expect(theme).toContain('font-size: var(--ath-font-size);')
    expect(theme).toContain('--text-body: 12px;')
  })
})
