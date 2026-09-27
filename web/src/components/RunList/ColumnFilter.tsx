/**
 * A run list column heading, and the filter it opens (D275).
 *
 * Every heading carries a funnel. It is drawn when the
 * pointer is over the heading, when it has the keyboard, and whenever
 * the column filters — a filter that is on is never invisible — and it
 * opens a popover anchored to the heading: `FILTER · STATUS` and how the
 * column matches (`any of`) over the column's control, then how many
 * runs are left, `clear` and `done`. A column that filters underlines
 * its heading; a `choice` column's funnel also carries how many choices
 * are on.
 *
 * WORKFLOW's choices are the same field the library's marks write
 * (`overlays/Library.tsx`), so a workflow checked here is marked there.
 *
 * Nothing here holds a filter. Every control writes `useUi.runFilter`,
 * which the list reads on its next render, so a row leaves as the key
 * that excluded it is pressed and the popover's count moves with it.
 *
 * An open popover owns the keyboard (`keys/scope.ts`): its checkboxes
 * and presets are buttons, and an `n` pressed on one must not open the
 * New Run overlay behind it.
 *
 * Below the breakpoint the headings are a strip of their own over the
 * two-line rows, funnels always drawn, each a 24 px touch target (WCAG
 * 2.5.8, 21 §Narrow layout).
 */
import { FunnelSimpleIcon } from '@phosphor-icons/react'
import { Popover } from 'radix-ui'
import { useState } from 'react'

import type { RunStatus } from '../../api/gen/types.gen'
import { useKeyOwner } from '../../keys'
import { cn } from '../../lib/utils'
import { useUi } from '../../store/ui'
import {
  AGE_PRESETS,
  KIND_MODE,
  TEXT_PLACEHOLDER,
  choiceOptions,
  clearColumn,
  columnActive,
  toLocalInput,
  toggled,
  type FilterColumn,
} from './filters'
import type { RunListModel } from './useRunList'
import { Frame } from '../Frame'

/** A count the server has not given yet (02 §Real data only). */
const UNKNOWN = '—'

/** The heading's label, underlined while its column filters. */
function Label({ column, active }: { column: FilterColumn; active: boolean }) {
  return (
    <span
      className={cn(
        'truncate',
        active &&
          'text-[var(--color-accent-200)] underline decoration-[var(--color-accent-500)] underline-offset-[3px]',
      )}
    >
      {column.label}
    </span>
  )
}

export function ColumnHeading({
  column,
  model,
  narrow,
}: {
  column: FilterColumn
  model: RunListModel
  narrow: boolean
}) {
  const filter = useUi((s) => s.runFilter)
  const [open, setOpen] = useState(false)
  useKeyOwner(open)

  const active = columnActive(filter, column.key)
  const right = column.key === 'age' && !narrow

  const selected =
    column.key === 'workflow'
      ? filter.workflows.length
      : column.key === 'status'
        ? filter.statuses.length
        : column.key === 'node'
          ? filter.nodes.length
          : 0
  const name = column.label.toLowerCase()

  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Anchor asChild>
        <span
          data-column={column.key}
          className={cn(
            'group relative flex min-w-0 items-center',
            right && 'justify-end',
            narrow && 'gap-[4px]',
          )}
        >
          <Label column={column} active={active} />
          <Popover.Trigger
            aria-label={`filter ${name}`}
            title={`filter ${name}`}
            data-shown={active || open}
            className={cn(
              'inline-flex cursor-pointer items-center justify-center gap-[3px] rounded-sm border px-[3px] tracking-normal',
              active || open
                ? 'border-[var(--color-accent-600)] bg-[var(--color-accent-900)] text-[var(--color-accent-100)]'
                : 'border-[var(--color-accent-800)] bg-[var(--color-neutral-900)] text-[var(--color-accent-300)] hover:bg-[var(--color-accent-800)] hover:text-[var(--color-accent-100)]',
              narrow
                ? 'min-h-[24px] min-w-[24px]'
                : cn(
                    'absolute top-1/2 h-[18px] min-w-[18px] -translate-y-1/2 transition-opacity',
                    right ? 'left-0' : 'right-0',
                    'pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 focus-visible:pointer-events-auto focus-visible:opacity-100 data-[shown=true]:pointer-events-auto data-[shown=true]:opacity-100',
                  ),
            )}
          >
            <FunnelSimpleIcon size={11} aria-hidden />
            {selected > 0 && <span className="text-hint leading-none">{selected}</span>}
          </Popover.Trigger>
        </span>
      </Popover.Anchor>
      <Popover.Portal>
        <Popover.Content
          align={right ? 'end' : 'start'}
          sideOffset={4}
          collisionPadding={12}
          aria-label={`filter ${name}`}
          data-testid="column-filter"
          className="text-meta z-50 w-[256px] max-w-[calc(100vw-24px)] rounded-lg border border-[var(--color-accent-700)] bg-card text-[var(--color-neutral-300)] shadow-[var(--shadow-lg)]"
        >
          <FilterPanel column={column} model={model} onDone={() => setOpen(false)} />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

/** The popover's body: title, the column's control, the tally and actions. */
function FilterPanel({
  column,
  model,
  onDone,
}: {
  column: FilterColumn
  model: RunListModel
  onDone: () => void
}) {
  const setRunFilter = useUi((s) => s.setRunFilter)

  return (
    <>
      <div className="flex items-center gap-[8px] border-b border-[var(--color-accent-900)] px-[10px] py-[7px]">
        <span className="text-hint tracking-[0.12em] text-[var(--color-accent-200)]">
          <Frame>FILTER · {column.label}</Frame>
        </span>
        <div className="flex-1" />
        <span className="text-hint text-muted-foreground">{KIND_MODE[column.kind]}</span>
      </div>

      {column.kind === 'text' && <TextControl column={column} onDone={onDone} />}
      {column.kind === 'choice' && <ChoiceControl column={column} model={model} />}
      {column.kind === 'date' && <DateControl now={model.now} />}

      <div className="flex items-center gap-[8px] border-t border-[var(--color-accent-900)] px-[10px] py-[6px]">
        <span data-testid="filter-tally" className="text-hint text-[var(--color-neutral-400)]">
          {model.rows.length} / {model.total ?? UNKNOWN} runs
        </span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={() => setRunFilter(clearColumn(column.key))}
          className="text-hint min-h-[24px] cursor-pointer rounded-sm border border-[var(--color-neutral-800)] px-[8px] text-[var(--color-neutral-400)] hover:border-[var(--color-accent-700)] hover:text-[var(--color-accent-200)]"
        >
          clear
        </button>
        <Popover.Close className="text-hint min-h-[24px] cursor-pointer rounded-sm border border-[var(--color-accent-600)] px-[10px] text-[var(--color-accent-200)] hover:bg-[var(--color-accent-900)]">
          done
        </Popover.Close>
      </div>
    </>
  )
}

/** RUN and TITLE: one box; `⏎` closes it, as `done` does. */
function TextControl({ column, onDone }: { column: FilterColumn; onDone: () => void }) {
  const filter = useUi((s) => s.runFilter)
  const setRunFilter = useUi((s) => s.setRunFilter)
  const value = column.key === 'id' ? filter.id : filter.title

  return (
    <div className="p-[10px]">
      <div className="flex items-center gap-[8px] rounded-sm border border-[var(--color-accent-800)] bg-background px-[8px] py-[6px]">
        <span aria-hidden className="text-[var(--color-accent-300)]">
          ~
        </span>
        <input
          type="text"
          value={value}
          onChange={(event) =>
            setRunFilter(
              column.key === 'id'
                ? { id: event.target.value }
                : { title: event.target.value },
            )
          }
          onKeyDown={(event) => {
            if (event.key === 'Enter') onDone()
          }}
          aria-label={`${column.label.toLowerCase()} contains`}
          placeholder={TEXT_PLACEHOLDER[column.key]}
          className="text-body min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-[var(--color-neutral-600)]"
        />
      </div>
    </div>
  )
}

/** STATUS and NODE: one checkbox per choice, with its faceted count. */
function ChoiceControl({ column, model }: { column: FilterColumn; model: RunListModel }) {
  const filter = useUi((s) => s.runFilter)
  const setRunFilter = useUi((s) => s.setRunFilter)
  const key =
    column.key === 'workflow' ? 'workflow' : column.key === 'status' ? 'status' : 'node'
  const options = choiceOptions(key, model.runs, filter, model.now)

  return (
    <div
      role="group"
      aria-label={`${column.label.toLowerCase()} choices`}
      className="max-h-[260px] overflow-y-auto py-[4px]"
    >
      {options.length === 0 && (
        <p className="px-[10px] py-[5px] text-muted-foreground">no runs to choose from</p>
      )}
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="checkbox"
          aria-checked={option.on}
          onClick={() =>
            setRunFilter(
              key === 'workflow'
                ? { workflows: toggled(filter.workflows, option.value) }
                : key === 'status'
                  ? { statuses: toggled(filter.statuses, option.value as RunStatus) }
                  : { nodes: toggled(filter.nodes, option.value) },
            )
          }
          className={cn(
            'text-row flex min-h-[24px] w-full cursor-pointer items-center gap-[8px] px-[10px] py-[4px] text-left hover:bg-[var(--color-neutral-900)]',
            option.on && 'bg-accent',
            option.count === 0 ? 'text-muted-foreground' : 'text-[var(--color-neutral-300)]',
          )}
        >
          <span
            aria-hidden
            className={cn(
              'flex-none',
              option.on ? 'text-[var(--color-accent-200)]' : 'text-[var(--color-accent-500)]',
            )}
          >
            {option.on ? '[x]' : '[ ]'}
          </span>
          <span className="min-w-0 flex-1 truncate">{option.label}</span>
          <span className="text-hint text-muted-foreground">{option.count}</span>
        </button>
      ))}
    </div>
  )
}

/**
 * AGE: four rolling windows, or a FROM/TO range of local datetimes.
 *
 * The two are one filter and not two: picking a window clears the range
 * and typing a range drops the window, so there is never a pair of
 * bounds on screen that is not the one the list is using.
 */
function DateControl({ now }: { now: number }) {
  const filter = useUi((s) => s.runFilter)
  const setRunFilter = useUi((s) => s.setRunFilter)
  const max = toLocalInput(now)
  const input =
    'text-meta min-w-0 rounded-sm border border-[var(--color-accent-800)] bg-background px-[6px] py-[4px] text-foreground [color-scheme:dark] outline-none focus-visible:border-[var(--color-accent-600)]'

  return (
    <div className="flex flex-col gap-[10px] p-[10px]">
      <div className="flex flex-wrap gap-[4px]">
        {AGE_PRESETS.map((preset) => {
          const on = filter.within === preset.ms
          return (
            <button
              key={preset.label}
              type="button"
              aria-pressed={on}
              onClick={() =>
                setRunFilter({ within: on ? null : preset.ms, after: '', before: '' })
              }
              className={cn(
                'text-hint min-h-[24px] cursor-pointer rounded-sm border px-[8px]',
                on
                  ? 'border-[var(--color-accent-600)] bg-accent text-[var(--color-accent-100)]'
                  : 'border-[var(--color-accent-800)] text-[var(--color-accent-300)] hover:border-[var(--color-accent-600)] hover:text-[var(--color-accent-100)]',
              )}
            >
              {preset.label}
            </button>
          )
        })}
      </div>
      <div className="grid grid-cols-[38px_minmax(0,1fr)] items-center gap-x-[8px] gap-y-[6px]">
        <span aria-hidden className="text-hint tracking-[0.1em] text-muted-foreground">
          FROM
        </span>
        <input
          type="datetime-local"
          aria-label="created from"
          value={filter.after}
          max={max}
          onChange={(event) => setRunFilter({ after: event.target.value, within: null })}
          className={input}
        />
        <span aria-hidden className="text-hint tracking-[0.1em] text-muted-foreground">
          TO
        </span>
        <input
          type="datetime-local"
          aria-label="created to"
          value={filter.before}
          max={max}
          onChange={(event) => setRunFilter({ before: event.target.value, within: null })}
          className={input}
        />
      </div>
    </div>
  )
}
