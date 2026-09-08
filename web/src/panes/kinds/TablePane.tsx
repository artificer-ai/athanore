/**
 * `table`: `{columns, rows}` as a sortable data table (09 §Panel kinds).
 *
 * shadcn's `Table` is the element, per 10 §Components ("shadcn `Table`
 * for plugin `table` kind"), dressed in the mock's zebra rows and 10 px
 * column kickers. The `dashboard` kind draws its optional table with
 * this same component, so a plugin's table sorts the same way wherever
 * it appears.
 *
 * **Sorting cycles through three states, not two.** A source's own row
 * order is information — the overview's NODES table is "the order the
 * run entered them" — so a third click puts it back rather than leaving
 * the operator to reload the pane to recover it.
 *
 * A column's `kind` is a hint about the value and not a format (09):
 * it decides alignment here, and nothing else. Numbers sort as numbers
 * because they *are* numbers on the wire, not because a column said so.
 */
import { useMemo, useState } from 'react'

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '../../components/ui/table'
import { cn } from '../../lib/utils'
import { compareValues, formatValue, nextSort, type Direction, type Sort } from './format'
import type { TableData } from './shape'

/** Column kinds whose values read right-aligned, as the mock draws them. */
const NUMERIC = new Set(['number', 'duration', 'tokens', 'cost'])

const ARIA_SORT: Record<Direction, 'ascending' | 'descending'> = {
  asc: 'ascending',
  desc: 'descending',
}

export function TablePane({
  data,
  label = 'panel data',
}: {
  data: TableData
  /** What a screen reader calls the table. */
  label?: string
}) {
  const [sort, setSort] = useState<Sort>(null)

  const rows = useMemo(() => {
    if (sort === null) return data.rows
    const sign = sort.direction === 'asc' ? 1 : -1
    return [...data.rows].sort(
      (a, b) => sign * compareValues(a[sort.key], b[sort.key]),
    )
  }, [data.rows, sort])

  if (data.columns.length === 0) {
    return (
      <p className="text-row text-muted-foreground" role="status">
        nothing to show
      </p>
    )
  }

  return (
    <div
      data-testid="pane-table"
      className="overflow-hidden rounded-lg border border-[var(--color-neutral-900)]"
    >
      <Table aria-label={label} className="text-row">
        <TableHeader>
          <TableRow className="border-[var(--color-neutral-900)] hover:bg-transparent">
            {data.columns.map((column) => {
              const sorted = sort?.key === column.key ? sort.direction : null
              return (
                <TableHead
                  key={column.key}
                  aria-sort={sorted === null ? 'none' : ARIA_SORT[sorted]}
                  className={cn(
                    'text-hint h-auto px-[8px] py-[5px] font-normal tracking-[0.06em] text-muted-foreground',
                    NUMERIC.has(column.kind ?? '') && 'text-right',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      setSort((current) => nextSort(current, column.key))
                    }}
                    className="cursor-pointer hover:text-[var(--color-accent-200)]"
                  >
                    {column.label ?? column.key}
                    <span aria-hidden="true">
                      {sorted === 'asc' ? ' ▲' : sorted === 'desc' ? ' ▼' : ''}
                    </span>
                  </button>
                </TableHead>
              )
            })}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row, index) => (
            <TableRow
              // Plugin rows carry no id (09 gives the shape as `[{…}]`),
              // so the index is the only identity there is.
              key={index}
              className={cn(
                'border-0 hover:bg-[var(--color-neutral-900)]',
                index % 2 === 1 && 'bg-zebra',
              )}
            >
              {data.columns.map((column) => (
                <TableCell
                  key={column.key}
                  className={cn(
                    'px-[8px] py-[4px] text-[var(--color-neutral-300)]',
                    NUMERIC.has(column.kind ?? '') && 'text-right text-muted-foreground',
                  )}
                >
                  {formatValue(row[column.key])}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
