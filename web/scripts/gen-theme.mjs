#!/usr/bin/env node
// Generate web/src/styles/theme.css — and the token list beside it,
// web/src/styles/tokens.gen.ts — from docs/v1/design/nocturne.css.
//
//   pnpm -C web gen:theme            write both files
//   pnpm -C web gen:theme --check    exit 1 if either is stale
//
// `docs/v1/design/nocturne.css` is the token source (AGENTS.md
// §Conventions: theme.css is generated, never hand-edited). This script
// copies its `--color-*`, `--space-*`, `--shadow-*` and `--ath-*`
// declarations verbatim — and the `ath-pulse` / `ath-caret` keyframes,
// but not `ath-scan` / `ath-flicker` (D71) — then appends the blocks
// that belong to the app rather than to Nocturne:
//
//   1. the shadcn/ui variables, mapped onto the tokens
//      (docs/v1/10-frontend.md §Tokens → shadcn — normative)
//   2. the `@theme inline` block that exposes those variables to
//      Tailwind v4 as colour, radius and font utilities
//   3. the app type base and the font-size steps the chooser picks
//      between (10 §Type and density, 21 §Type scale)
//   4. the status colour utilities of 10 §Status colours
//   5. the type scale utilities of 10 §Type and density
//   6. the chrome and zebra surfaces of 10 §Type and density
//   7. the two animations, each disabled under reduced motion
//      (10 §Accessibility and quality)
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

/**
 * The same tokens as data, for `/__tokens` to render. A stylesheet is
 * not readable from a component — Vite hands `?raw` on a `.css` file to
 * the Tailwind plugin, which returns the compiled sheet or nothing —
 * so the list is generated beside the sheet from the same parse.
 */
export const TOKENS_TARGET = resolve(WEB, 'src/styles/tokens.gen.ts')

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
 * The `@keyframes NAME { ... }` rule Nocturne declares, verbatim, with
 * the source's alignment padding collapsed to one space.
 *
 * Nocturne declares four; only two of them are the app's (D71), so the
 * name is asked for rather than swept up. A missing one is an error:
 * silently emitting no animation is how the running pill stops pulsing
 * without anyone noticing.
 *
 * @param {string} css
 * @param {string} name
 * @returns {string}
 */
function parseKeyframes(css, name) {
  const head = new RegExp(`@keyframes\\s+${name}\\s*\\{`).exec(css)
  if (!head) throw new Error(`${SOURCE}: no @keyframes ${name}`)

  let depth = 0
  for (let i = head.index + head[0].length - 1; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1
    else if (css[i] === '}') {
      depth -= 1
      if (depth === 0) {
        const body = css.slice(head.index + head[0].length - 1, i + 1)
        return `@keyframes ${name} ${body}`
      }
    }
  }
  throw new Error(`${SOURCE}: unterminated @keyframes ${name}`)
}

/**
 * The status colours of 10 §Status colours, in that table's order:
 * `[suffix, value, the states it paints]`.
 *
 * Every one but `paused` is an `--ath-status-*` token; `paused` is not
 * in the mock and 10 gives it the nearest role in the ramps.
 * `assertStatusColours` keeps this list and the source in step.
 */
const STATUS_COLOURS = [
  ['ok', 'var(--ath-status-ok)', 'completed / done'],
  ['active', 'var(--ath-status-active)', 'running / in_progress'],
  ['gate', 'var(--ath-status-gate)', 'waiting on a human'],
  ['queued', 'var(--ath-status-queued)', 'queued / ready'],
  ['fail', 'var(--ath-status-fail)', 'failed / dead_letter'],
  ['muted', 'var(--ath-status-muted)', 'cancelled'],
  ['paused', 'var(--color-accent-2-400)', 'paused (10: nearest role)'],
]

/**
 * Every `--ath-status-*` token in the source has a utility above.
 *
 * The list is written out because 10's table has an order and a
 * `paused` row Nocturne does not; this is what stops a status colour
 * added to the source from reaching the app as no utility at all.
 *
 * @param {{name: string}[]} tokens
 */
function assertStatusColours(tokens) {
  const painted = new Set(STATUS_COLOURS.map(([suffix]) => `--ath-status-${suffix}`))
  const missing = tokens
    .map((token) => token.name)
    .filter((name) => name.startsWith('--ath-status-') && !painted.has(name))
  if (missing.length > 0) {
    throw new Error(
      `${SOURCE}: ${missing.join(', ')} has no utility; add the row to ` +
        "STATUS_COLOURS (and to 10 §Status colours' table)",
    )
  }
}

/**
 * The mock's base, in pixels: the denominator of the whole ramp.
 *
 * It is a constant of the scale and not a read of `--ath-font-size`
 * (21 §Type scale). The token is what `<html>` is *set* to and what the
 * chooser's steps multiply; this is what every step of the ramp was
 * measured against when the mock was drawn, so `text-row` is 11.5/12 of
 * whatever the base becomes, for ever.
 */
const BASE_PX = 12

/**
 * One `font-size` declaration of the ramp, as an exact fraction of the
 * base (21 §Type scale's table).
 *
 * `calc(11.5rem / 12)` rather than `0.9583rem`: the form is exact, and a
 * reader can see the mock's pixel value in it. The base itself is `1rem`
 * rather than `calc(12rem / 12)` for the same reason — that is what the
 * fraction says.
 *
 * @param {number} px the size the mock draws at the default base
 * @returns {string}
 */
function size(px) {
  return px === BASE_PX
    ? 'font-size: 1rem;'
    : `font-size: calc(${px}rem / ${BASE_PX});`
}

/**
 * The type scale of 10 §Type and density: `[suffix, declarations]`.
 *
 * These are `@utility` rules rather than `--text-*` entries in
 * `@theme`, because Tailwind derives a `text-NAME` font-size utility
 * from such an entry and `text-kicker` is a size *and* a transform and
 * a tracking — one name cannot come from both places.
 *
 * For the same reason the 11 px step is `text-meta`, not the
 * `text-secondary` T057 first named: `secondary` is a shadcn colour role
 * (10 §Tokens → shadcn maps it onto `--color-surface`), Tailwind derives
 * `.text-secondary { color: var(--secondary) }` from it, and the two
 * rules land on one class — an 11 px size that also paints the text the
 * surface colour, and beats a colour utility written beside it (D151).
 * `assertNoRoleCollision` is what keeps that from coming back.
 */
const TYPE_SCALE = [
  ['metric', [size(15), 'font-weight: 500;'], 'metric values'],
  ['body', [size(12)], 'body copy, the base itself'],
  ['row', [size(11.5)], 'table and list rows'],
  ['meta', [size(11)], "10's 11 px secondary text: ids, chrome, meta lines"],
  [
    'kicker',
    [size(10.5), 'text-transform: uppercase;', 'letter-spacing: 0.12em;'],
    'section kickers: STATS, NODES, EVENT LOG',
  ],
  ['hint', [size(10)], 'key hints and column headers'],
]

/**
 * The two surfaces 10 §Type and density mixes out of the tokens: the
 * chrome strips (header, list header, pane bar, footer) and the zebra
 * of alternating rows and tool blocks.
 */
const SURFACES = [
  ['chrome', 45, 'header, list header, pane bar, footer'],
  ['zebra', 60, 'alternating rows, tool blocks'],
]

/**
 * The status colour utilities. Text and border only: 10 uses a status
 * colour for the label, the graph glyph and the outline of a
 * `Badge variant="outline"`, and never as a fill.
 */
function statusBlock() {
  return STATUS_COLOURS.flatMap(([suffix, value, states]) => [
    `/* ${states} */`,
    `@utility text-status-${suffix} { color: ${value}; }`,
    `@utility border-status-${suffix} { border-color: ${value}; }`,
    '',
  ])
    .slice(0, -1)
    .join('\n')
}

/** The type scale utilities. */
function typeScaleBlock() {
  return TYPE_SCALE.map(
    ([suffix, declarations, use]) =>
      `/* ${use} */\n@utility text-${suffix} { ${declarations.join(' ')} }`,
  ).join('\n\n')
}

/** The chrome and zebra surfaces. */
function surfaceBlock() {
  return SURFACES.map(
    ([suffix, percent, use]) =>
      `/* ${use} */\n@utility bg-${suffix} {\n  background-color: color-mix(` +
      `in srgb, var(--color-surface) ${percent}%, var(--color-bg));\n}`,
  ).join('\n\n')
}

/**
 * The two animations the mock keeps (D71), their keyframes copied from
 * the source and their timings taken from 10 §Status colours (the
 * 1.8 s pulse) and the mock's caret.
 *
 * The `prefers-reduced-motion` guard is part of this block, not a later
 * pass: 10 §Accessibility and quality says the pulse and the caret stop
 * under it. The guard is unlayered, so it beats the utilities Tailwind
 * emits into `@layer utilities` whatever the source order.
 *
 * @param {string} nocturne
 */
function motionBlock(nocturne) {
  return `${parseKeyframes(nocturne, 'ath-pulse')}
${parseKeyframes(nocturne, 'ath-caret')}

/* Running status (10 §Status colours) and the agent stream's caret. */
@utility animate-ath-pulse { animation: ath-pulse 1.8s ease-in-out infinite; }
@utility animate-ath-caret { animation: ath-caret 1s step-end infinite; }

@media (prefers-reduced-motion: reduce) {
  .animate-ath-pulse,
  .animate-ath-caret {
    animation: none;
  }
}`
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
 * worse than no utility. The status colours, the type scale and the two
 * surfaces are not here either — they are `@utility` rules further
 * down, because each of them is more than one declaration.
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

  /* Type scales, density does not (D195, 21 §Type scale). Tailwind's
     own spacing scale is 0.25rem a step, which would grow with the base
     the chooser sets and take every padding and gap in the app with it;
     3 px is what that step already resolves to at the mock's 12 px base,
     so this pins the density where it is without moving a pixel. */
  --spacing: 3px;

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
  --font-heading: 'JetBrains Mono Variable', var(--ath-font-mono);`

/**
 * The utility prefixes Tailwind builds out of the `--color-*` namespace.
 * A `@utility` named `<prefix><role>` for a role in `@theme inline`
 * shares its class with the derived colour utility, and both rules
 * apply: the class carries a `color` (or a `background-color`, or a
 * `border-color`) nobody asked for, and it beats a colour utility
 * written beside it. `text-secondary` against `--color-secondary` is how
 * that was found (D151).
 */
const COLOUR_UTILITY_PREFIXES = [
  'text-',
  'bg-',
  'border-',
  'ring-',
  'outline-',
  'fill-',
  'stroke-',
  'decoration-',
  'divide-',
  'caret-',
  'accent-',
  'shadow-',
  'from-',
  'via-',
  'to-',
  'placeholder-',
]

/**
 * No `@utility` in the generated stylesheet shares a name with a colour
 * utility Tailwind derives from `@theme inline`.
 *
 * The two halves of this file are written in different places — the
 * shadcn roles from 10 §Tokens → shadcn, the type scale and the status
 * colours from 10 §Type and density — and nothing else notices when a
 * name appears in both. Renaming the utility is the fix; the roles are
 * shadcn's and cannot move.
 *
 * @param {string} css the generated stylesheet
 */
function assertNoRoleCollision(css) {
  const roles = new Set(
    [...THEME_INLINE.matchAll(/^\s*--color-([a-z0-9-]+)\s*:/gm)].map(
      (match) => match[1],
    ),
  )
  for (const [, utility] of css.matchAll(/@utility ([a-z0-9-]+)/g)) {
    for (const prefix of COLOUR_UTILITY_PREFIXES) {
      if (!utility.startsWith(prefix)) continue
      const role = utility.slice(prefix.length)
      if (!roles.has(role)) continue
      throw new Error(
        `${TARGET}: @utility ${utility} collides with the shadcn role ` +
          `--color-${role}, which Tailwind already derives .${utility} from — ` +
          'one class name, two rules, and the colour comes along. Rename the ' +
          'utility (D151).',
      )
    }
  }
}

/**
 * The chooser's four steps, as multipliers of `--ath-font-size`
 * (21 §Type scale's second table, D195): `[step, numerator]` over
 * {@link BASE_PX}.
 *
 * `default` is not here because `default` is the absence of the
 * attribute — the `html` rule above is it — which is what makes an
 * operator who has never touched the chooser, and one who has set it
 * back, the same operator.
 *
 * They multiply the token rather than naming pixels so that a
 * re-imported base flows through them unedited: change
 * `--ath-font-size` in `nocturne.css` and all four steps move with it.
 */
const FONT_SIZE_STEPS = [
  ['small', 11],
  ['large', 13.5],
  ['xlarge', 15],
]

/**
 * The base the whole ramp is a fraction of: one face, one line height,
 * and the four sizes the chooser picks between (10 §Type and density,
 * 21 §Type scale).
 *
 * The SPA writes `data-font-size` on `<html>` from `usePrefs.fontSize`
 * before first paint (D196); no component reads the preference to style
 * itself, because everything under here is already relative to this
 * declaration. Line-height stays unitless, so it scales for free.
 *
 * **Type scales, density does not** (D195): the spacing, the borders and
 * the mock's pixel chrome are absolute, and `--spacing` in the
 * `@theme inline` block above is what holds Tailwind's own scale still.
 */
const TYPE_BASE = `@layer base {
  html {
    font-size: var(--ath-font-size);
    line-height: 1.5;
  }

${FONT_SIZE_STEPS.map(
  ([step, numerator]) =>
    `  html[data-font-size='${step}'] {\n` +
    `    font-size: calc(var(--ath-font-size) * ${numerator} / ${BASE_PX});\n` +
    '  }',
).join('\n')}
}`

/**
 * @param {string} nocturne the contents of docs/v1/design/nocturne.css
 * @returns {string} the contents of web/src/styles/theme.css
 */
export function renderTheme(nocturne) {
  const tokens = parseRootTokens(nocturne)
  assertStatusColours(tokens)
  const css = `/* GENERATED by web/scripts/gen-theme.mjs — do not edit by hand.
 *
 * Built from nocturne.css, the design system's token sheet; the
 * generator names where it lives. Regenerate with
 * \`pnpm -C web gen:theme\`; the gate fails while this file and its
 * source disagree (web/src/styles/theme.test.ts).
 *
 * Four layers:
 *   1. the Nocturne tokens, copied verbatim from the source
 *   2. the shadcn/ui variables, mapped onto them
 *   3. the Tailwind \`@theme inline\` exposure, the type base and the
 *      four sizes the font-size chooser picks between
 *   4. the utilities the mock styles from: the status colours, the type
 *      scale, the two mixed surfaces and the two animations
 *
 * Every utility here reads a token; none of them is a hex. \`/__tokens\`
 * (dev only) renders all of it on one page.
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

/* --- App type base and the chooser's steps (10 §Type and density) --- */

${TYPE_BASE}

/* --- Status colours (10 §Status colours) --- */

${statusBlock()}

/* --- Type scale (10 §Type and density) --- */

${typeScaleBlock()}

/* --- Surfaces (10 §Type and density) --- */

${surfaceBlock()}

/* --- Motion (D71; 10 §Accessibility and quality) --- */

${motionBlock(nocturne)}
`
  assertNoRoleCollision(css)
  return css
}

/**
 * The tokens of the generated stylesheet as a TypeScript module, so the
 * `/__tokens` page can list them without hard-coding a copy that drifts.
 * It is read back out of the stylesheet this run produced, which is what
 * makes the two files two views of one parse.
 *
 * @param {string} css the contents of web/src/styles/theme.css
 * @returns {string} the contents of web/src/styles/tokens.gen.ts
 */
export function renderTokensModule(css) {
  /** A TypeScript string literal, single-quoted like the rest of `web/`. */
  const quote = (/** @type {string} */ text) =>
    /['\\]/.test(text) ? JSON.stringify(text) : `'${text}'`

  const rows = parseRootTokens(css).map(({ name, value }) => {
    const family = PREFIXES.some((prefix) => name.startsWith(prefix))
      ? 'nocturne'
      : 'shadcn'
    return (
      `  { name: ${quote(name)}, value: ${quote(value)}, ` + `family: '${family}' },`
    )
  })
  return `/* GENERATED by web/scripts/gen-theme.mjs — do not edit by hand.
 *
 * Every custom property ./theme.css declares, in source order, for
 * src/dev/Tokens.tsx to render at /__tokens. Regenerate both with
 * \`pnpm -C web gen:theme\`.
 */

/** One custom property of theme.css: Nocturne's, or a shadcn role. */
export type ThemeToken = {
  name: string
  value: string
  family: 'nocturne' | 'shadcn'
}

export const THEME_TOKENS: ThemeToken[] = [
${rows.join('\n')}
]
`
}

function main() {
  const check = process.argv.includes('--check')
  const css = renderTheme(readFileSync(SOURCE, 'utf8'))
  /** @type {[string, string][]} */
  const wanted = [
    [TARGET, css],
    [TOKENS_TARGET, renderTokensModule(css)],
  ]

  if (check) {
    for (const [path, contents] of wanted) {
      let current = null
      try {
        current = readFileSync(path, 'utf8')
      } catch (error) {
        if (/** @type {NodeJS.ErrnoException} */ (error).code !== 'ENOENT') throw error
      }
      if (current === contents) continue
      process.stderr.write(
        `${path} is stale: it does not match what gen-theme.mjs builds from\n` +
          `${SOURCE}. Run \`pnpm -C web gen:theme\` and commit the result.\n`,
      )
      process.exitCode = 1
      return
    }
    return
  }

  for (const [path, contents] of wanted) {
    mkdirSync(dirname(path), { recursive: true })
    writeFileSync(path, contents)
    process.stderr.write(`wrote ${path}\n`)
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main()
