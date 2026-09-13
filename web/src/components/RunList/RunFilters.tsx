/**
 * The run list's two controls, which the mock puts in the header strip:
 * the workflow chips and the `/` filter input (10 §Layout).
 *
 * They live in this module rather than beside `Header` because they are
 * the run list's — they narrow its rows and nothing else — and because
 * the state they write is read by the grid two components away. `Header`
 * only says where on the strip they go.
 *
 * The chips are a Radix `ToggleGroup` in single mode (10 §Components),
 * which makes them a radio group: exactly one is on, `all` when no
 * workflow is. Deselecting the active chip therefore falls back to `all`
 * rather than leaving the list filtered by nothing at all.
 *
 * Below the breakpoint the two sit in the header's scrolling strip (21
 * §Narrow layout), so the chips stop wrapping — a strip that wraps is
 * not a strip — and both grow to a 24 px touch target (WCAG 2.5.8).
 */
import { ToggleGroup } from 'radix-ui'

import { ALL_WORKFLOWS, useUi } from '../../store/ui'

export function RunFilters({ workflows }: { workflows: readonly string[] }) {
  const filter = useUi((s) => s.runFilter)
  const setRunWorkflow = useUi((s) => s.setRunWorkflow)
  const setRunQuery = useUi((s) => s.setRunQuery)

  return (
    <>
      <ToggleGroup.Root
        type="single"
        value={filter.workflow}
        onValueChange={(value) => setRunWorkflow(value === '' ? ALL_WORKFLOWS : value)}
        aria-label="filter by workflow"
        className="flex flex-wrap items-center gap-[5px] max-md:flex-none max-md:flex-nowrap"
      >
        {[ALL_WORKFLOWS, ...workflows].map((workflow) => (
          <ToggleGroup.Item
            key={workflow}
            value={workflow}
            className="rounded-lg border border-border px-[8px] py-[3px] text-[calc(10.5rem/12)] text-muted-foreground hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)] data-[state=on]:border-[var(--color-accent-600)] data-[state=on]:bg-accent data-[state=on]:text-[var(--color-accent-200)] max-md:min-h-[24px] max-md:whitespace-nowrap"
          >
            {workflow}
          </ToggleGroup.Item>
        ))}
      </ToggleGroup.Root>

      <div className="flex min-w-[190px] items-center gap-[8px] rounded-lg border border-border bg-card px-[8px] py-[4px] max-md:flex-none">
        <span aria-hidden className="text-muted-foreground">
          /
        </span>
        <input
          type="text"
          value={filter.query}
          onChange={(event) => setRunQuery(event.target.value)}
          aria-label="filter runs"
          placeholder="filter runs"
          className="text-meta w-full bg-transparent text-foreground outline-none placeholder:text-[var(--color-neutral-600)] max-md:min-h-[24px]"
        />
      </div>
    </>
  )
}
