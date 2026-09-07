/**
 * The token page is checked by eye against the mock, but two things
 * about it are mechanical and belong in the gate: it must show every
 * token the generated stylesheet declares, and it must name every
 * utility that stylesheet generates — Tailwind emits a utility only when
 * it finds the class as literal text in a source file, so a class this
 * page assembles at runtime would render unstyled.
 */
import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Tokens } from './Tokens'

const HERE = dirname(fileURLToPath(import.meta.url))
const theme = readFileSync(resolve(HERE, '../styles/theme.css'), 'utf8')
const source = readFileSync(resolve(HERE, 'Tokens.tsx'), 'utf8')

/** Every `@utility NAME {` the generated stylesheet declares. */
function generatedUtilities(): string[] {
  return [...theme.matchAll(/@utility ([a-z0-9-]+) \{/g)].map((match) => match[1] ?? '')
}

/** Every `--name` declared in the generated `:root` block. */
function generatedTokens(): string[] {
  const body = /:root \{([\s\S]*?)\n\}/.exec(theme)?.[1] ?? ''
  return [...body.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gim)].map((match) => match[1] ?? '')
}

describe('the token page', () => {
  it('names every utility theme.css generates, as literal text', () => {
    const utilities = generatedUtilities()
    expect(utilities.length).toBeGreaterThan(20)
    for (const utility of utilities) {
      expect(source, `${utility} is not on the page`).toContain(utility)
    }
  })

  it('renders every token theme.css declares', () => {
    render(<Tokens />)
    const tokens = generatedTokens()
    expect(tokens.length).toBeGreaterThan(50)
    for (const token of tokens) {
      expect(screen.getByText(token), `${token} is not on the page`).toBeVisible()
    }
  })

  it('shows the status colours of 10 §Status colours', () => {
    render(<Tokens />)
    for (const state of [
      'completed / done',
      'running / in_progress',
      'waiting (gate)',
      'queued / ready',
      'failed / dead_letter',
      'cancelled',
      'paused',
    ]) {
      // A one-word state also names its pill, so there are two of it.
      const [swatch] = screen.getAllByText(state)
      expect(swatch, `${state} is not on the page`).toBeVisible()
    }
  })
})
