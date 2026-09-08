/**
 * The router: one route, `/`, whose search parameters are the whole of
 * the app's shareable state (`docs/v1/10-frontend.md` §Layout).
 *
 * There is deliberately no second route. Overlays, the selected run and
 * the pane index are all search parameters, which is what makes every
 * view linkable, and the search is validated field by field, dropping
 * what it does not recognise rather than throwing (`./search.ts`).
 */
import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  defaultParseSearch,
  type RouterHistory,
} from '@tanstack/react-router'

import { AppRoute, NotFoundRedirect } from './AppRoute'
import { validateAppSearch, type AppSearch } from './search'

/**
 * Parse the location's query string straight into {@link AppSearch}.
 *
 * A route's `validateSearch` is not on its own enough to keep an
 * unrecognised key out of the app. A match carries two searches, and the
 * one every hook reads — `useSearch`, `useLocation`, the `prev` handed to
 * a `navigate({search})` updater — is `match.search`, which router-core
 * computes as `{...parentSearch, ...validatedSearch}`. The parent chain
 * bottoms out in the raw parse of the query string, so a key the
 * validator drops is merged straight back in underneath it: `?run=123`
 * reaches the app as a number and `?run={"a":1}` as an object, which
 * React renders by throwing.
 *
 * Validating here puts the drop *before* the merge, where there is
 * nothing left to leak. The whole SPA is one route, so the location's
 * search and the app's search are the same object, and every match
 * inherits it already validated. The URL itself is left alone: a
 * bookmark keeps whatever it carried, and the app never sees it.
 */
function parseAppSearch(searchStr: string): AppSearch {
  return validateAppSearch(defaultParseSearch(searchStr))
}

const rootRoute = createRootRoute({ component: Outlet })

export const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: '/',
  validateSearch: validateAppSearch,
  component: AppRoute,
})

export const routeTree = rootRoute.addChildren([indexRoute])

/** A router over the given history; the browser's when none is given. */
export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    ...(history === undefined ? {} : { history }),
    parseSearch: parseAppSearch,
    defaultNotFoundComponent: NotFoundRedirect,
  })
}

export const router = createAppRouter()

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createAppRouter>
  }
}
