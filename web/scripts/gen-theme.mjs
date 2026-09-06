#!/usr/bin/env node
// Generate web/src/styles/theme.css from docs/v1/design/nocturne.css.
//
//   pnpm -C web gen:theme            write the file
//   pnpm -C web gen:theme --check    exit 1 if it is stale
//
// `docs/v1/design/nocturne.css` is the token source (AGENTS.md
// §Conventions: theme.css is generated, never hand-edited). This script
// copies its `--color-*`, `--space-*`, `--shadow-*` and `--ath-*`
// declarations verbatim, then appends three hand-written blocks that
// belong to the app rather than to Nocturne:
//
//   1. the shadcn/ui variables, mapped onto the tokens
//      (docs/v1/10-frontend.md §Tokens → shadcn — normative)
//   2. the `@theme inline` block that exposes those variables to
//      Tailwind v4 as colour, radius and type utilities
//   3. the app type scale (12 px base, JetBrains Mono;
//      10 §Type and density)
//
// `web/src/styles/theme.test.ts` runs `--check` as part of `pnpm test`,
// so a hand edit or a change to nocturne.css that was not regenerated
// fails the gate and CI.

import { readFileSync, writeFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const WEB = resolve(dirname(fileURLToPath(import.meta.url)), '..')
export const SOURCE = resolve(WEB, '../docs/v1/design/nocturne.css')
export const TARGET = resolve(WEB, 'src/styles/theme.css')

/** The token families copied out of Nocturne, in the plan's order. */
const PREFIXES = ['--color-', '--space-', '--shadow-', '--ath-']

/** One `--name: value;` line, with any trailing comment kept. */
const DECLARATION = /^\s*(--[a-z0-9-]+)\s*:\s*([^;]+?)\s*;\s*(\/\*.*\*\/)?\s*$/i

/**
 * Every custom property declared in a `:root` block of `css`, in source
 * order.
 *
 * Nocturne is a committed, hand-formatted file with one declaration per
 * line, so a line scan is enough — but a value that ever wraps would be
 * dropped silently, so the count is checked against a scan of the whole
 * block afterwards.
 *
 * @param {string} css
 * @returns {{name: string, value: string, comment: string | null}[]}
 */
function parseRootTokens(css) {
  const tokens = []
  let declarationsSeen = 0
  let depth = 0
  let inRoot = false

  for (const line of css.split('\n')) {
    if (!inRoot) {
      if (/^\s*:root\s*\{/.test(line)) {
        inRoot = true
        depth = 1
      }
      continue
    }

    depth += (line.match(/\{/g) ?? []).length
    depth -= (line.match(/\}/g) ?? []).length
    if (depth <= 0) {
      inRoot = false
      continue
    }

    if (/^\s*--[a-z0-9-]+\s*:/i.test(line)) declarationsSeen += 1
    const match = DECLARATION.exec(line)
    if (!match) continue
    const [, name, value, comment] = match
    tokens.push({ name, value, comment: comment ?? null })
  }

  if (inRoot) throw new Error(`${SOURCE}: unterminated :root block`)
  if (tokens.length !== declarationsSeen) {
    throw new Error(
      `${SOURCE}: ${declarationsSeen} declarations in :root but only ` +
        `${tokens.length} parsed — a value that wraps onto a second line ` +
        'would be dropped; reformat the source or teach this parser about it',
    )
  }
  return tokens
}

/**
 * The Nocturne block: every token whose name starts with one of
 * PREFIXES, grouped by family so the generated file reads like the
 * source it came from.
 *
 * @param {{name: string, value: string, comment: string | null}[]} tokens
 */
function nocturneBlock(tokens) {
  const lines = []
  for (const prefix of PREFIXES) {
    const family = tokens.filter((token) => token.name.startsWith(prefix))
    if (family.length === 0) {
      throw new Error(`${SOURCE}: no ${prefix}* tokens; the source changed shape`)
    }
    if (lines.length > 0) lines.push('')
    for (const { name, value, comment } of family) {
      lines.push(`  ${name}: ${value};${comment ? ` ${comment}` : ''}`)
    }
  }
  return lines.join('\n')
}

/**
 * The shadcn/ui variables, on the Nocturne tokens. Every row of
 * 10 §Tokens → shadcn is here; the `-foreground` companions the table
 * does not name are derived from the same tokens so that no shadcn
 * component can reference an undefined variable.
 */
const SHADCN_MAPPING = `  --background: var(--color-bg);
  --foreground: var(--color-text);

  --card: var(--color-surface);
  --card-foreground: var(--color-text);
  --popover: var(--color-surface);
  --popover-foreground: var(--color-text);
  --secondary: var(--color-surface);
  --secondary-foreground: var(--color-text);

  --muted: var(--color-neutral-900);
  --muted-foreground: var(--color-neutral-500);

  /* Accent is a border and a text colour, never a fill (Nocturne). */
  --primary: var(--color-accent);
  --primary-foreground: var(--color-accent-200);
  --accent: color-mix(in srgb, var(--color-accent) 16%, transparent);
  --accent-foreground: var(--color-accent-200);

  --destructive: var(--ath-status-fail);
  --destructive-foreground: var(--color-bg);

  /* Chrome and inputs sit on --color-bg with a neutral-800 rule. */
  --border: var(--color-neutral-800);
  --input: var(--color-neutral-800);
  --ring: var(--color-accent);

  /* Nocturne's 8 px (its --radius-md). The app does not override it
     with the mock's old 2 px — that went with the CRT chrome (D71). */
  --radius: 8px;

  --chart-1: var(--color-accent);
  --chart-2: var(--color-accent-700);
  --chart-3: var(--color-accent-2-400);`

/**
 * Tailwind v4 reads `@theme`, not `:root`, so the variables above reach
 * the utility layer through this block. `inline` keeps the utilities
 * pointing at the `:root` variables rather than at a copy, which is what
 * makes `color-mix(...)` and the token indirection survive.
 *
 * shadcn's `sidebar-*` and `chart-4`/`chart-5` roles are deliberately
 * absent: 10 §Tokens → shadcn defines three chart colours and no
 * sidebar, and a utility pointing at a variable nothing declares is
 * worse than no utility.
 */
const THEME_INLINE = `  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-destructive-foreground: var(--destructive-foreground);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --color-chart-1: var(--chart-1);
  --color-chart-2: var(--chart-2);
  --color-chart-3: var(--chart-3);

  --radius-sm: calc(var(--radius) * 0.6);
  --radius-md: calc(var(--radius) * 0.8);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) * 1.4);
  --radius-2xl: calc(var(--radius) * 1.8);
  --radius-3xl: calc(var(--radius) * 2.2);
  --radius-4xl: calc(var(--radius) * 2.6);

  /* One face (10 §Type and density). The bundled variable font first,
     then the families --ath-font-mono names. */
  --font-mono: 'JetBrains Mono Variable', var(--ath-font-mono);
  --font-sans: 'JetBrains Mono Variable', var(--ath-font-mono);
  --font-heading: 'JetBrains Mono Variable', var(--ath-font-mono);

  /* The mock's sizes, named for what they label. Line height is 1.5
     throughout, set once on <html> below. */
  --text-metric: 15px;
  --text-body: 12px;
  --text-row: 11.5px;
  --text-secondary: 11px;
  --text-kicker: 10.5px;
  --text-hint: 10px;`

/** 12 px base, one face, one line height (10 §Type and density). */
const TYPE_SCALE = `@layer base {
  html {
    font-size: var(--ath-font-size);
    line-height: 1.5;
  }
}`

/**
 * @param {string} nocturne the contents of docs/v1/design/nocturne.css
 * @returns {string} the contents of web/src/styles/theme.css
 */
export function renderTheme(nocturne) {
  const tokens = parseRootTokens(nocturne)
  return `/* GENERATED by web/scripts/gen-theme.mjs — do not edit by hand.
 *
 * Source: docs/v1/design/nocturne.css. Regenerate with
 * \`pnpm -C web gen:theme\`; the gate fails while this file and the
 * source disagree (web/src/styles/theme.test.ts).
 *
 * Three layers, per docs/v1/10-frontend.md §Design system:
 *   1. the Nocturne tokens, copied verbatim from the source
 *   2. the shadcn/ui variables, mapped onto them (§Tokens → shadcn)
 *   3. the Tailwind \`@theme inline\` exposure and the app type scale
 *
 * The Nocturne names \`--color-neutral-*\` and \`--shadow-*\` are also
 * Tailwind v4 theme namespaces. This file is imported after
 * \`tailwindcss\` and is unlayered, so it wins: \`border-neutral-800\` and
 * \`shadow-md\` render Nocturne's values, not Tailwind's defaults. That is
 * the intent — nothing in a component hard-codes a hex.
 */

:root {
${nocturneBlock(tokens)}

  /* --- shadcn/ui, on the tokens above (10 §Tokens → shadcn) --- */

${SHADCN_MAPPING}
}

/* --- Tailwind utilities (10 §Design system) --- */

@theme inline {
${THEME_INLINE}
}

/* --- App type scale (10 §Type and density) --- */

${TYPE_SCALE}
`
}

function main() {
  const check = process.argv.includes('--check')
  const wanted = renderTheme(readFileSync(SOURCE, 'utf8'))

  if (check) {
    let current = null
    try {
      current = readFileSync(TARGET, 'utf8')
    } catch (error) {
      if (/** @type {NodeJS.ErrnoException} */ (error).code !== 'ENOENT') throw error
    }
    if (current === wanted) return
    process.stderr.write(
      `${TARGET} is stale: it does not match what gen-theme.mjs builds from\n` +
        `${SOURCE}. Run \`pnpm -C web gen:theme\` and commit the result.\n`,
    )
    process.exitCode = 1
    return
  }

  mkdirSync(dirname(TARGET), { recursive: true })
  writeFileSync(TARGET, wanted)
  process.stderr.write(`wrote ${TARGET}\n`)
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main()
