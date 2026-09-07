/**
 * `/__tokens` — the design system on one page, in dev only.
 *
 * T057 has no Storybook (docs/v1/17-serial-task-plan.md § T057): this is
 * where the theme is checked by eye against `docs/v1/design/Athanore.dc.html`
 * before any screen is built on it. It renders
 *
 *   - every custom property `web/src/styles/theme.css` declares, read
 *     from `../styles/tokens.gen.ts` — the list `pnpm gen:theme` writes
 *     beside the stylesheet — so a token added to
 *     `docs/v1/design/nocturne.css` shows up here without an edit; and
 *   - every utility that file generates, written out as a literal class
 *     name — Tailwind scans source text, so a class assembled at runtime
 *     would never be emitted. `Tokens.test.tsx` fails if the generated
 *     stylesheet grows a utility this page does not name.
 *
 * `main.tsx` reaches it with a dynamic import behind `import.meta.env.DEV`,
 * so none of this is in the production bundle.
 */
import type { ReactNode } from 'react'

import { THEME_TOKENS, type ThemeToken } from '../styles/tokens.gen'

/** Kept in step with the literal in `main.tsx`, which must not import this. */
const PATH = '/__tokens'

/** How a token is best shown: as a colour, a length, a shadow, or as text. */
function kindOf({ name, value }: ThemeToken): 'colour' | 'length' | 'shadow' | 'text' {
  const lengths = ['--radius', '--ath-radius', '--ath-font-size']
  if (name.startsWith('--shadow-')) return 'shadow'
  if (name.startsWith('--space-') || lengths.includes(name)) return 'length'
  if (value.includes('monospace')) return 'text'
  return 'colour'
}

function Preview({ token }: { token: ThemeToken }) {
  const reference = `var(${token.name})`
  switch (kindOf(token)) {
    case 'colour':
      return (
        <span
          aria-hidden
          className="h-6 w-6 flex-none rounded-md border border-border"
          style={{ background: reference }}
        />
      )
    case 'length':
      return (
        <span aria-hidden className="flex h-6 w-6 flex-none items-center justify-end">
          <span
            className="h-3 bg-[var(--color-accent-400)]"
            style={{ width: reference }}
          />
        </span>
      )
    case 'shadow':
      return (
        <span
          aria-hidden
          className="h-6 w-6 flex-none rounded-md bg-card"
          style={{ boxShadow: reference }}
        />
      )
    case 'text':
      return <span aria-hidden className="h-6 w-6 flex-none" />
  }
}

function TokenRow({ token }: { token: ThemeToken }) {
  return (
    <div className="flex items-center gap-3 overflow-hidden">
      <Preview token={token} />
      <code className="text-row text-foreground">{token.name}</code>
      <span className="text-hint truncate text-muted-foreground">{token.value}</span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="text-kicker mb-3 text-muted-foreground">{title}</h2>
      {children}
    </section>
  )
}

/** The type scale of the generated stylesheet, one literal class each. */
const TYPE_SCALE = [
  { cls: 'text-metric', note: '15 px / 500 — metric values' },
  { cls: 'text-body', note: '12 px — body copy, the base' },
  { cls: 'text-row', note: '11.5 px — table and list rows' },
  { cls: 'text-meta', note: '11 px — secondary text: ids, chrome, meta lines' },
  { cls: 'text-kicker', note: '10.5 px uppercase, .12em — section kickers' },
  { cls: 'text-hint', note: '10 px — key hints and column headers' },
]

/** The status colours of 10 §Status colours, in that table's order. */
const STATUSES = [
  { state: 'completed / done', text: 'text-status-ok', border: 'border-status-ok' },
  {
    state: 'running / in_progress',
    text: 'text-status-active',
    border: 'border-status-active',
  },
  { state: 'waiting (gate)', text: 'text-status-gate', border: 'border-status-gate' },
  {
    state: 'queued / ready',
    text: 'text-status-queued',
    border: 'border-status-queued',
  },
  {
    state: 'failed / dead_letter',
    text: 'text-status-fail',
    border: 'border-status-fail',
  },
  { state: 'cancelled', text: 'text-status-muted', border: 'border-status-muted' },
  { state: 'paused', text: 'text-status-paused', border: 'border-status-paused' },
]

export function Tokens() {
  return (
    <main className="text-body min-h-dvh bg-background p-6 text-foreground">
      <header className="mb-8 flex flex-wrap items-baseline gap-3">
        <h1 className="text-body font-bold tracking-[0.12em] text-[var(--color-accent-300)]">
          ▚ ATHANORE
        </h1>
        <span className="text-meta text-muted-foreground">
          {PATH} — every token and utility in src/styles/theme.css, generated from
          docs/v1/design/nocturne.css
        </span>
      </header>

      <Section title="Nocturne tokens">
        <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
          {THEME_TOKENS.filter((token) => token.family === 'nocturne').map((token) => (
            <TokenRow key={token.name} token={token} />
          ))}
        </div>
      </Section>

      <Section title="shadcn roles">
        <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2 xl:grid-cols-3">
          {THEME_TOKENS.filter((token) => token.family === 'shadcn').map((token) => (
            <TokenRow key={token.name} token={token} />
          ))}
        </div>
      </Section>

      <Section title="Type scale">
        <div className="flex flex-col gap-2">
          {TYPE_SCALE.map(({ cls, note }) => (
            <div key={cls} className="flex flex-wrap items-baseline gap-3">
              <span className={`${cls} w-72 flex-none`}>
                {cls === 'text-kicker' ? 'event log' : 'Athanore 0123456789'}
              </span>
              <code className="text-hint text-muted-foreground">
                .{cls} — {note}
              </code>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Status colours">
        <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 xl:grid-cols-3">
          {STATUSES.map(({ state, text, border }) => (
            <div key={state} className="flex items-center gap-3">
              <span
                className={`text-hint rounded-md border px-1.5 py-px ${text} ${border}`}
              >
                {state.split(' ')[0]}
              </span>
              <span className={`text-row ${text}`}>{state}</span>
              <code className="text-hint truncate text-muted-foreground">
                .{text} .{border}
              </code>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Surfaces">
        <div className="max-w-3xl overflow-hidden rounded-md border border-border">
          <div className="text-hint bg-chrome flex items-center gap-3 border-b border-border px-3 py-1.5 text-muted-foreground">
            <span>.bg-chrome</span>
            <span>header · list header · pane bar · footer</span>
          </div>
          <div className="text-row bg-card px-3 py-1">.bg-card — surface</div>
          <div className="text-row bg-zebra px-3 py-1">.bg-zebra — alternating row</div>
          <div className="text-row bg-card px-3 py-1">.bg-card — surface</div>
          <div className="text-row bg-zebra px-3 py-1">.bg-zebra — alternating row</div>
          <div className="text-row bg-background px-3 py-1">.bg-background — page</div>
        </div>
      </Section>

      <Section title="Motion">
        <div className="flex flex-wrap items-center gap-6">
          <span className="text-row flex items-center gap-2">
            <span
              aria-hidden
              className="animate-ath-pulse h-1.5 w-1.5 rounded-full bg-primary"
            />
            .animate-ath-pulse — running
          </span>
          <span className="text-row flex items-center gap-2">
            <span aria-hidden className="animate-ath-caret inline-block h-3 w-2 bg-primary" />
            .animate-ath-caret — agent stream
          </span>
          <span className="text-hint text-muted-foreground">
            both stop under prefers-reduced-motion
          </span>
        </div>
      </Section>

      <Section title="Primitives">
        <div className="flex flex-wrap items-start gap-8">
          <div className="grid grid-cols-3 gap-px bg-[var(--color-neutral-900)]">
            {[
              ['tasks', '128'],
              ['running', '3'],
              ['p95', '1.4s'],
            ].map(([label, value]) => (
              <div key={label} className="bg-card px-2.5 py-2">
                <div className="text-hint tracking-[0.1em] text-muted-foreground">
                  {label}
                </div>
                <div className="text-metric mt-0.5">{value}</div>
              </div>
            ))}
          </div>
          <div className="flex items-center gap-2">
            {['^p', 'b', 'esc'].map((key) => (
              <span
                key={key}
                className="text-hint rounded-md border border-border bg-[var(--color-neutral-900)] px-1 text-[var(--color-accent-300)]"
              >
                {key}
              </span>
            ))}
            <span className="text-hint text-muted-foreground">key hints</span>
          </div>
          <button
            type="button"
            className="text-meta rounded-md border border-primary px-2.5 py-1 text-primary hover:bg-accent"
          >
            ＋ new run
          </button>
        </div>
      </Section>
    </main>
  )
}
