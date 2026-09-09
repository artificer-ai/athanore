/**
 * The accessibility gate: axe over a page, and the number T068a asks for.
 *
 * 10 §Accessibility and quality asks for "Lighthouse a11y ≥ 95 on the
 * dashboard"; T068a names `@axe-core/playwright` as what measures it.
 * axe reports rules rather than a score, so this module is the
 * translation, and it is written down here because it is a choice the
 * documents did not make (D178):
 *
 * - the **score** is the share of the rules axe actually evaluated on
 *   this page that passed — `passes / (passes + violations)` as a
 *   percentage. A rule that does not apply to the page is neither, and
 *   counting it either way would make the number a fact about the
 *   markup's shape rather than about its quality;
 * - **no violation may be `serious` or `critical`**, whatever the score
 *   says. A ratio alone would let one rule that makes the app unusable
 *   with a screen reader hide behind thirty that passed, and that is
 *   the failure the gate exists to catch.
 *
 * {@link violationReport} is what a failure prints: the rule, its
 * impact, and the first selector it fired on, so a red gate names the
 * element rather than a number.
 */
import type AxeBuilder from '@axe-core/playwright'

/** The results `AxeBuilder.analyze()` resolves to. */
export type AxeResults = Awaited<ReturnType<AxeBuilder['analyze']>>

/** One rule axe found something wrong with. */
type Violation = AxeResults['violations'][number]

/** The threshold of 10 §Accessibility and quality, as a percentage. */
export const A11Y_SCORE = 95

/** The impacts no violation may carry, whatever the score is. */
export const BLOCKING_IMPACTS = ['serious', 'critical']

/** The share of evaluated rules that passed, as a percentage. */
export function axeScore(results: AxeResults): number {
  const evaluated = results.passes.length + results.violations.length
  if (evaluated === 0) return 0
  return (100 * results.passes.length) / evaluated
}

/** The violations whose impact is one the gate refuses outright. */
export function blocking(results: AxeResults): Violation[] {
  return results.violations.filter(
    (violation) => violation.impact != null && BLOCKING_IMPACTS.includes(violation.impact),
  )
}

/** Every violation, one line each, for the failure message. */
export function violationReport(results: AxeResults): string {
  if (results.violations.length === 0) return 'no violations'
  return results.violations
    .map((violation) => {
      const where = violation.nodes[0]?.target.join(' ') ?? '(no node)'
      return `${violation.id} [${violation.impact ?? 'unknown'}] ${violation.help} — ${where}`
    })
    .join('\n')
}
