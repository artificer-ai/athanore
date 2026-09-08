/**
 * The run list's data: `GET /api/runs`, and the view of it the header
 * chips and the `/` input have narrowed.
 *
 * One query backs the whole left half of the app and the header's two
 * counts (`docs/v1/10-frontend.md` §Layout). It is the generated one, so
 * its key is the key `src/realtime/invalidate.ts` invalidates on `run.*`
 * and `task.*` — that is the whole of "the list updates when a run is
 * submitted from the CLI", and there is no interval anywhere.
 *
 * Filtering is client-side, over the list the server returned whole (08
 * §Conventions): `?status` and `?workflow` exist on the endpoint and are
 * deliberately not used, because a second query key per chip would be a
 * second cache entry for the same rows and the invalidation table knows
 * about one.
 */
import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { listRunsApiRunsGetOptions } from '../../api/gen/@tanstack/react-query.gen'
import type { RunStatus, RunSummary } from '../../api/gen/types.gen'
import { ALL_WORKFLOWS, useUi } from '../../store/ui'
import { humaniseAge } from './age'
import { statusTone, type StatusTone } from './status'

/** How many characters of a run's ULID the RUN column shows (T061). */
export const SHORT_ID_LENGTH = 8

/** How often the AGE column recomputes, in milliseconds. */
export const AGE_TICK_MS = 1000

/** What the NODE column reads when a run is in no node. */
export const NO_NODE = '—'

/** The run status that counts towards the header's `● k active`. */
export const ACTIVE_STATUS: RunStatus = 'running'

/** One row of the grid, with every cell already resolved to a string. */
export type RunRow = {
  id: string
  shortId: string
  workflow: string
  title: string
  status: RunStatus
  tone: StatusTone
  node: string
  pendingRequests: number
  age: string
}

/** What the run list, the header and the collapsed rail all read. */
export type RunListModel = {
  /** The rows the chip and the filter left, in dispatch order. */
  rows: RunRow[]
  /** Every run the server returned, or `null` before it has answered. */
  total: number | null
  /** Runs in progress, or `null` before the server has answered. */
  active: number | null
  /** The workflows there are runs of, for the chip group. */
  workflows: string[]
  /** Whether the first answer is still outstanding. */
  isPending: boolean
  /** Whether the request failed. */
  isError: boolean
}

/**
 * `GET /api/runs`, cached.
 *
 * `queryFn` is put back explicitly for the reason `useMe` does it
 * (`src/api/client.ts`): the generator declares it optional and
 * `exactOptionalPropertyTypes` will not assign an optional-and-absent
 * property onto `useQuery`'s required one.
 */
export function useRuns() {
  const { queryFn, ...options } = listRunsApiRunsGetOptions()
  return useQuery({ ...options, queryFn: queryFn! })
}

/**
 * A clock that ticks once a second, for the AGE column.
 *
 * It fetches nothing: ages are `now − created` and the finest unit the
 * column prints is a second, so a row that never re-rendered would show
 * a number that is quietly wrong. Everything else on the row moves when
 * an event invalidates the query.
 */
export function useNow(intervalMs: number = AGE_TICK_MS): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])

  return now
}

/** Whether `run` matches the `/` input: its title or its id contains it. */
export function matchesQuery(run: RunSummary, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (needle === '') return true
  return (
    run.title.toLowerCase().includes(needle) || run.id.toLowerCase().includes(needle)
  )
}

/** One `RunSummary` as the grid draws it. */
export function toRow(run: RunSummary, now: number): RunRow {
  const nodes = run.current_nodes ?? []
  const pendingRequests = run.pending_requests ?? 0

  return {
    id: run.id,
    shortId: run.id.slice(0, SHORT_ID_LENGTH),
    workflow: run.workflow,
    title: run.title,
    status: run.status,
    tone: statusTone(run.status, pendingRequests),
    node: nodes.length === 0 ? NO_NODE : nodes.join(' · '),
    pendingRequests,
    age: humaniseAge(run.created, now),
  }
}

/**
 * The whole model, derived from the query and the filter.
 *
 * The workflow chips are the workflows there *are* runs of, sorted by
 * name: a chip for a registered workflow nobody has run would filter the
 * list to nothing, and first-appearance order would reshuffle the header
 * every time a run was submitted or moved.
 */
export function useRunListModel(): RunListModel {
  const { data, isPending, isError } = useRuns()
  const filter = useUi((s) => s.runFilter)
  const now = useNow()

  const runs = data ?? []
  const workflows = [...new Set(runs.map((run) => run.workflow))].sort((a, b) =>
    a.localeCompare(b),
  )
  const rows = runs
    .filter(
      (run) =>
        (filter.workflow === ALL_WORKFLOWS || run.workflow === filter.workflow) &&
        matchesQuery(run, filter.query),
    )
    .map((run) => toRow(run, now))

  return {
    rows,
    total: data === undefined ? null : data.length,
    active:
      data === undefined
        ? null
        : data.filter((run) => run.status === ACTIVE_STATUS).length,
    workflows,
    isPending,
    isError,
  }
}
