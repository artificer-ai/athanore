/**
 * `GET /api/runs/{id}`, as the panes that need more than their own
 * source read it.
 *
 * Two of them do, and for the same reason: a builtin's route answers
 * with what its kind declares, and the ids and statuses behind those
 * values are the wire contract's own resource rather than something a
 * panel route should send a second copy of (09 §Context and scopes). The
 * overview reads it for the attempt a NODES row opens the drawer on; the
 * agent pane reads it for the attempt whose transcript it draws.
 *
 * The generated query, so its key is the one the invalidation table
 * refreshes on `run.*`, `task.*` and `agent.stats` (10 §Realtime and
 * caching) — one cache entry, so two panes of one run cannot disagree
 * about which attempt is running. `queryFn` is put back explicitly for
 * the reason `useRuns` does it (`src/api/client.ts`): the generator
 * declares it optional and `exactOptionalPropertyTypes` will not assign
 * an optional-and-absent property onto `useQuery`'s required one.
 */
import { useQuery } from '@tanstack/react-query'

import { getRunApiRunsRunIdGetOptions } from '../../api/gen/@tanstack/react-query.gen'
import type { RunDetail } from '../../api/gen/types.gen'

/** The run in scope, or `undefined` until it has arrived. */
export function useRunDetail(runId: string | undefined): RunDetail | undefined {
  const { queryFn, ...options } = getRunApiRunsRunIdGetOptions({
    path: { run_id: runId ?? '' },
  })
  const { data } = useQuery({
    ...options,
    queryFn: queryFn!,
    enabled: runId !== undefined,
  })
  return data
}
