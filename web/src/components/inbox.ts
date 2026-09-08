/**
 * What the inbox reads and the order it draws it in (`./Inbox.tsx`).
 *
 * Separate from the component for the reason `panes/kinds/requests.ts`
 * is separate from the pane that uses it: a module exporting both a
 * component and a function is one React Fast Refresh cannot update in
 * place (`.oxlintrc.json`, `react/only-export-components`).
 */
import { useQuery } from '@tanstack/react-query'

import { listRequestsApiRequestsGetOptions } from '../api/gen/@tanstack/react-query.gen'
import type { RequestView } from '../api/gen/types.gen'

/**
 * `GET /api/requests`: the inbox, with the route's own `pending=true`.
 *
 * **No options, deliberately.** The key the generator builds carries
 * whatever options the query was asked with, so a query that spelled
 * `pending=true` out would sit in a different cache entry from
 * `queryKeys.inbox()` — the entry `request.*` invalidates (10 §Realtime
 * and caching) and the one `RequestPanel` refetches after it answers.
 * The route's default is `pending=true` (08 §Requests), which is exactly
 * what the inbox wants, so the two agree by asking for nothing.
 *
 * `queryFn` is put back explicitly for the reason `panes/kinds/run.ts`
 * gives: the generator declares it optional and
 * `exactOptionalPropertyTypes` will not assign an optional-and-absent
 * property onto `useQuery`'s required one.
 */
export function useInbox() {
  const { queryFn, ...options } = listRequestsApiRequestsGetOptions()
  return useQuery({ ...options, queryFn: queryFn! })
}

/**
 * The requests newest first: by the moment they were opened, and by id
 * when two share it.
 *
 * A history reads forwards and a queue of things waiting on you reads
 * with the freshest at the top, which is what 06 §SPA asks of the inbox
 * and the opposite of what a run's own pane does. `GET /api/requests`
 * answers oldest first and says that is not a presentation
 * (`athanore/store/repos/requests.py`), so the order is made here.
 *
 * Ids are the store's own increasing integers, so they are the honest
 * tie-break for two requests opened inside one clock tick — which a node
 * that asks twice in a row does routinely.
 */
export function newestFirst(requests: readonly RequestView[]): RequestView[] {
  return [...requests].sort((a, b) => {
    const byTime = b.created.localeCompare(a.created)
    return byTime !== 0 ? byTime : b.id - a.id
  })
}
