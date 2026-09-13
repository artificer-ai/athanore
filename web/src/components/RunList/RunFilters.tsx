/**
 * The run list's three controls, which the mock puts in the header
 * strip: the workflow chips, the status chips and the `/` filter input
 * (10 §Layout).
 *
 * They live in this module rather than beside `Header` because they are
 * the run list's — they narrow its rows and nothing else — and because
 * the state they write is read by the grid two components away. `Header`
 * only says where on the strip they go.
 *
 * The workflow chips are a Radix `ToggleGroup` in single mode (10
 * §Components), which makes them a radio group: exactly one is on, `all`
 * when no workflow is. Deselecting the active chip therefore falls back
 * to `all` rather than leaving the list filtered by nothing at all.
 *
 * The status chips are a second `ToggleGroup`, in multiple mode: one
 * chip per run status of 03, any number of them on, and a run is listed
 * when its status is one of them. There is no floor — every one may be
 * off, and the list then reads `0 shown` — because a chip that refused
 * the last toggle would be a chip that ignores a click. The `all` beside
 * that group is a `Toggle` of its own and not a member of it, since
 * "select all" is not a status: it is drawn on only while every status
 * is, pressing it turns every status on, and pressing it while it is on
 * changes nothing. Its accessible name is `all statuses`, so it is told
 * apart from the workflow group's `all`. On every load `completed` and
 * `cancelled` start off (D268; `DEFAULT_RUN_STATUSES`).
 *
 * Every chip wears the one look — neutral off, accent-tinted on — and
 * not the status colours: a chip is a filter control, and the pill on
 * the row is where a status is coloured (10 §Status colours).
 *
 * In multiple mode Radix draws the group as a `toolbar` and each chip
 * as a `button` with `aria-pressed`, and roving focus is on in both
 * groups: `tab` reaches a group, `←`/`→` move within it, `space`/`⏎`
 * toggle the chip under focus (10 §Keyboard).
 *
 * Below the breakpoint the three sit in the header's scrolling strip
 * (21 §Narrow layout), so the chips stop wrapping — a strip that wraps
 * is not a strip — and every control grows to a 24×24 px touch target
 * (WCAG 2.5.8).
 */
import { Toggle, ToggleGroup } from 'radix-ui'

import { ALL_WORKFLOWS, RUN_STATUSES, useUi } from '../../store/ui'

/** The chips of 10 §Components: outlined, accent-tinted when on. */
const CHIP =
  'cursor-pointer rounded-lg border border-border px-[8px] py-[3px] ' +
  'text-[calc(10.5rem/12)] text-muted-foreground ' +
  'hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-200)] ' +
  'data-[state=on]:border-[var(--color-accent-600)] data-[state=on]:bg-accent ' +
  'data-[state=on]:text-[var(--color-accent-200)] ' +
  'max-md:min-h-[24px] max-md:min-w-[24px] max-md:whitespace-nowrap'

/** A group of chips: wrapping above the breakpoint, one line below it. */
const GROUP = 'flex flex-wrap items-center gap-[5px] max-md:flex-none max-md:flex-nowrap'

export function RunFilters({ workflows }: { workflows: readonly string[] }) {
  const filter = useUi((s) => s.runFilter)
  const setRunWorkflow = useUi((s) => s.setRunWorkflow)
  const setRunStatuses = useUi((s) => s.setRunStatuses)
  const setRunQuery = useUi((s) => s.setRunQuery)

  const allStatusesOn = RUN_STATUSES.every((status) => filter.statuses.includes(status))

  return (
    <>
      <ToggleGroup.Root
        type="single"
        value={filter.workflow}
        onValueChange={(value) => setRunWorkflow(value === '' ? ALL_WORKFLOWS : value)}
        aria-label="filter by workflow"
        className={GROUP}
      >
        {[ALL_WORKFLOWS, ...workflows].map((workflow) => (
          <ToggleGroup.Item key={workflow} value={workflow} className={CHIP}>
            {workflow}
          </ToggleGroup.Item>
        ))}
      </ToggleGroup.Root>

      <span aria-hidden className="text-[var(--color-neutral-800)]">
        │
      </span>

      <div className="flex items-center gap-[5px] max-md:flex-none">
        {/* One-way: it turns every status on and never off — a chip
            that turned everything off would leave an empty list one tap
            from a full one (D268 (1)). */}
        <Toggle.Root
          pressed={allStatusesOn}
          onPressedChange={() => setRunStatuses(RUN_STATUSES)}
          aria-label="all statuses"
          className={CHIP}
        >
          all
        </Toggle.Root>
        <ToggleGroup.Root
          type="multiple"
          value={filter.statuses}
          onValueChange={setRunStatuses}
          aria-label="filter by status"
          className={GROUP}
        >
          {RUN_STATUSES.map((status) => (
            <ToggleGroup.Item key={status} value={status} className={CHIP}>
              {status}
            </ToggleGroup.Item>
          ))}
        </ToggleGroup.Root>
      </div>

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
