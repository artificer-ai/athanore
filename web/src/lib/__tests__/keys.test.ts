/**
 * `lib/keys.ts` against the specification's keyboard map.
 *
 * The map is one sentence, and it is quoted here verbatim: the test
 * pulls every keycap out of the quotation and asserts the table carries
 * all of them. That is the only check that catches the failure this
 * table exists to prevent — a binding in the spec that nobody
 * transcribed — because a test that walked the table would agree with
 * whatever the table happened to say.
 *
 * `capLabel` is the other half and is checked against the table rather
 * than against the quotation: it is how a cap is *drawn*, which 10
 * states about the map and not in it (D207).
 */
import { describe, expect, it } from 'vitest'

import {
  capLabel,
  FOOTER_HINTS,
  KEY_BINDINGS,
  KEY_GROUPS,
  SHIFT_CAP,
  bindingsOf,
} from '../keys'

/**
 * 10 §Keyboard, quoted.
 *
 * If this ever disagrees with the document, the document wins and both
 * this string and the table change together.
 */
const SPEC = [
  '`↑`/`↓` or `j`/`k` select, `⇧↑`/`⇧↓` move run, `←`/`→` cycle panes,',
  '`1`–`9` jump, `tab` focus, `t` retry task, `m` move task, `x` cancel task, `l`',
  'append log, `n` new run, `r` rerun node, `p` pause/resume, `c` cancel run,',
  '`D` (shift) delete run (with confirm), `e` edit run, `w` workflows, `b`',
  'toggle list, `?` keys, `^p` palette, `^r` refresh,',
  '`esc` close overlay / clear run.',
  'Requests add `a` allow / `d` deny when the request panel has focus.',
].join(' ')

/** Every keycap the quotation puts in backticks. */
function specKeys(): string[] {
  return [...SPEC.matchAll(/`([^`]+)`/g)].map((match) => match[1]!)
}

/**
 * Every keycap the table draws, with the one range expanded.
 *
 * `1`–`9` is one binding — "jump to a pane" is one thing an operator
 * does — drawn as the single cap `1–9`, so the two ends the spec names
 * are matched against it here rather than making nine rows of it.
 */
function tableKeys(): Set<string> {
  const keys = new Set<string>()
  for (const binding of KEY_BINDINGS) {
    for (const key of binding.keys) {
      if (key === '1–9') {
        keys.add('1')
        keys.add('9')
      } else {
        keys.add(key)
      }
    }
  }
  return keys
}

describe('the keyboard map', () => {
  it('carries every keycap 10 §Keyboard names', () => {
    const table = tableKeys()

    for (const key of specKeys()) {
      expect(table, `10 §Keyboard names \`${key}\``).toContain(key)
    }
  })

  it('invents no keycap 10 §Keyboard does not name', () => {
    const spec = new Set(specKeys())

    for (const key of tableKeys()) {
      expect(spec, `the table draws \`${key}\``).toContain(key)
    }
  })

  it('draws `⇧↑`/`⇧↓` as move run, with the modifier in the cap', () => {
    // 10 §Keyboard: "`⇧↑`/`⇧↓` move the selected run in the dispatch
    // order". A shifted arrow's `event.key` is the plain arrow's, so
    // the chord is what is bound and the chip is in the table itself
    // rather than added by `capLabel` (D274). It is a row of its own
    // and not a condition on `select`: there is no mode, and `⏎` binds
    // nothing any more.
    const move = KEY_BINDINGS.find((binding) => binding.id === 'move-run')

    expect(move?.keys).toEqual([`${SHIFT_CAP}↑`, `${SHIFT_CAP}↓`])
    expect(move?.label).toBe('move run')
    expect(move?.note).toBe('')
    expect(KEY_BINDINGS.some((binding) => binding.id === 'focus-run')).toBe(false)
    expect(KEY_BINDINGS.some((binding) => binding.id === 'focus-detail')).toBe(false)
  })

  it('binds delete to D, never to the mock’s d', () => {
    const del = KEY_BINDINGS.find((binding) => binding.id === 'delete-run')
    const deny = KEY_BINDINGS.find((binding) => binding.id === 'deny')

    // 10 §Keyboard: "Delete moved from `d` to `D` so a `d` meant for
    // 'deny' that lands one focus ring away cannot reach the delete
    // confirm."
    expect(del?.keys).toEqual(['D'])
    expect(deny?.keys).toEqual(['d'])
    expect(del?.note).toContain('asks first')
  })

  it('scopes the request-panel keys, which is their whole rule', () => {
    for (const id of ['allow', 'deny']) {
      const binding = KEY_BINDINGS.find((one) => one.id === id)
      expect(binding?.group).toBe('requests')
      expect(binding?.note).toBe('while the request panel has focus')
    }
  })

  it('gives every row a unique id, at least one cap, and a label', () => {
    const ids = KEY_BINDINGS.map((binding) => binding.id)
    expect(new Set(ids).size).toBe(ids.length)

    for (const binding of KEY_BINDINGS) {
      expect(binding.keys.length).toBeGreaterThan(0)
      expect(binding.label).not.toBe('')
      expect(KEY_GROUPS).toContain(binding.group)
    }
  })

  it('splits into groups that partition the table, in its order', () => {
    expect(KEY_GROUPS.flatMap((group) => bindingsOf(group))).toEqual(KEY_BINDINGS)
  })

  it('is the footer strip’s row, in the map’s order', () => {
    // The mock's footer, with 10 §Keyboard's one correction: `D`.
    expect(FOOTER_HINTS.map((hint) => [hint.keys, hint.label])).toEqual([
      [['tab'], 'focus'],
      [['t'], 'retry task'],
      [['m'], 'move task'],
      [['x'], 'cancel task'],
      [['l'], 'append log'],
      [['n'], 'new run'],
      [['r'], 'rerun node'],
      [['p'], 'pause/resume'],
      [['c'], 'cancel run'],
      [['D'], 'delete run'],
      [['e'], 'edit run'],
      [['w'], 'workflows'],
      [['b'], 'toggle list'],
      [['?'], 'keys'],
    ])
  })
})

describe('capLabel', () => {
  it('draws the one capital of the map with a shift chip', () => {
    // The table binds `D` and the three views draw `⇧D`: a bare capital
    // in an all-lowercase interface reads as `d`, which is the request
    // panel's deny and reaches nothing else (D51, D207).
    expect(capLabel('D')).toBe('⇧D')
    expect(SHIFT_CAP).toBe('⇧')
  })

  it('changes `D` and nothing else the table draws', () => {
    const relabelled = [...tableKeys()].filter((key) => capLabel(key) !== key)

    expect(relabelled).toEqual(['D'])
  })

  it('leaves every other notation of the map alone', () => {
    for (const cap of ['^p', '^r', '?', '⇧↑', 'esc', 'tab', '1–9', 'd', '—']) {
      expect(capLabel(cap), `capLabel(\`${cap}\`)`).toBe(cap)
    }
    for (const arrow of ['↑', '↓', '←', '→']) {
      expect(capLabel(arrow), `capLabel(\`${arrow}\`)`).toBe(arrow)
    }
  })
})
