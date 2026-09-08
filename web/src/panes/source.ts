/**
 * A panel's `source`: the request it makes, the key that request is
 * cached under, and the `refresh_on` names that make it stale
 * (`docs/v1/09-plugins.md` §Wire contract, `docs/v1/10-frontend.md`
 * §Realtime and caching).
 *
 * A plugin route is *not* part of the committed wire contract — which
 * routes exist depends on what is installed (09 §Builtins are plugins) —
 * so there is no generated operation for it and none could be generated.
 * The manifest carries the mounted URL instead and the SPA fetches it
 * "through the generated client's `fetch`" (09 §Wire contract): the same
 * client, the same base URL, the same credential and the same 401
 * interceptor as every typed call, with only the URL supplied by data.
 *
 * Two things follow from that and are the whole of this file:
 *
 * - **the parameters are the scope's, not the caller's.** 09 §Context
 *   and scopes resolves a route's context from its `run_id` / `task_id`
 *   / `node` query parameters, and a panel declares the `scope` that has
 *   to be resolved before it can load. So a `run`-scoped panel is asked
 *   with `run_id` and nothing else, and a panel whose scope has no id
 *   yet is not asked at all rather than being asked for a 404 (D158).
 * - **the key is the source and its parameters.** `['panel', source]` is
 *   a prefix of every scoped instance of that panel, which is what lets
 *   `refresh_on` be registered once, at manifest load, against a panel
 *   whose run is not known yet — the same prefix property the generated
 *   keys have (D155).
 */
import { useQuery, type QueryKey } from '@tanstack/react-query'
import { useEffect } from 'react'

import { client } from '../api/gen/client.gen'
import type { PanelOut, PluginManifestEntry } from '../api/gen/types.gen'
import { clearRefreshOn, registerRefreshOn } from '../realtime/invalidate'

/**
 * The kinds whose data comes from a `source` URL (09 §Panel kinds).
 *
 * `form`'s `source` names an action rather than a route, `custom` has an
 * element instead of a source, and a kind this build does not know has a
 * shape it does not know either — so none of the three is fetched, and
 * `PaneRenderer` draws all three from the manifest entry alone.
 */
export const DATA_KINDS: ReadonlySet<string> = new Set([
  'markdown',
  'kv',
  'table',
  'log',
  'chart',
  'dashboard',
])

/** The URL a panel's data comes from, or `null` if it has none. */
export function panelSource(panel: PanelOut): string | null {
  return DATA_KINDS.has(panel.kind) ? (panel.source ?? null) : null
}

/** The ids the SPA has to offer a panel: the selection, and the drawer. */
export type PanelScope = {
  /** The selected run, from `?run=`. */
  runId?: string | undefined
  /** The focused attempt, from `?task=`. */
  taskId?: number | undefined
}

/** The query string a panel's route is asked with (09 §Context). */
export type PanelParams = {
  run_id?: string
  task_id?: number
  node?: string
}

/**
 * The parameters `panel` is asked with in `scope`, or `null` when its
 * scope cannot be resolved yet.
 *
 * `null` is a real state and not an error: the pane host draws a
 * `run`-scoped panel the moment `?run=` names a run, and a `task`-scoped
 * one belongs to the task drawer, which may have no task in it. Asking
 * anyway would spend a request on a 404 the server is right to give
 * (09 §Context and scopes lists a missing id as a 404 before the handler
 * runs), so the pane says what it is waiting for instead.
 */
export function panelParams(panel: PanelOut, scope: PanelScope): PanelParams | null {
  switch (panel.scope) {
    case 'global':
    case 'workflow':
      return {}
    case 'run':
      return scope.runId === undefined ? null : { run_id: scope.runId }
    case 'task':
      if (scope.taskId === undefined) return null
      return {
        ...(scope.runId === undefined ? {} : { run_id: scope.runId }),
        task_id: scope.taskId,
      }
    case 'node':
      if (scope.runId === undefined || panel.node == null) return null
      return { run_id: scope.runId, node: panel.node }
  }
}

/**
 * The cache key of a panel's data.
 *
 * With no parameters it is the prefix every scoped instance shares,
 * which is what {@link registerPanelRefresh} registers: TanStack matches
 * a filter key partially, so invalidating `['panel', source]` reaches
 * this run's copy and every other run's.
 */
export function panelQueryKey(source: string, params?: PanelParams): QueryKey {
  return params === undefined ? ['panel', source] : ['panel', source, params]
}

/**
 * What a panel's source answered with, when it did not answer with data.
 *
 * The generated client throws the parsed error body and drops the
 * status, and a pane that only said "failed" would leave the operator
 * guessing between a plugin that raised, a run that is gone and a server
 * that is not there. This carries both, and `ErrorCard` shows them.
 */
export class PanelSourceError extends Error {
  readonly status: number | undefined
  readonly code: string | undefined

  constructor(message: string, status?: number, code?: string) {
    super(message)
    this.name = 'PanelSourceError'
    this.status = status
    this.code = code
  }
}

/** The API's one error shape: `{error, code}` (08 §Conventions). */
function errorMessage(body: unknown, response: Response | undefined): string {
  if (typeof body === 'string' && body.trim() !== '') return body
  if (typeof body === 'object' && body !== null) {
    const error = (body as { error?: unknown }).error
    if (typeof error === 'string' && error !== '') return error
  }
  if (response !== undefined) return `${String(response.status)} ${response.statusText}`
  return 'the request failed'
}

function errorCode(body: unknown): string | undefined {
  if (typeof body === 'object' && body !== null) {
    const code = (body as { code?: unknown }).code
    if (typeof code === 'string' && code !== '') return code
  }
  return undefined
}

/** `GET <source>?<params>`, as a {@link PanelSourceError} or its data. */
export async function fetchPanel(
  source: string,
  params: PanelParams,
): Promise<unknown> {
  const result = await client.get<unknown, unknown>({ url: source, query: params })
  if (result.error !== undefined || result.response?.ok !== true) {
    throw new PanelSourceError(
      errorMessage(result.error, result.response),
      result.response?.status,
      errorCode(result.error),
    )
  }
  return result.data
}

/**
 * A panel's data, cached and invalidated like everything else.
 *
 * Disabled — rather than fetched and discarded — for a panel with no
 * source ({@link DATA_KINDS}) and for a scope that is not resolved yet.
 */
export function usePanelSource(panel: PanelOut, params: PanelParams | null) {
  const source = panelSource(panel)
  const enabled = source !== null && params !== null

  return useQuery({
    queryKey: panelQueryKey(source ?? '', params ?? {}),
    queryFn: () => fetchPanel(source ?? '', params ?? {}),
    enabled,
  })
}

/**
 * Register every panel's `refresh_on` names against its query key.
 *
 * "Plugin panels register their `refresh_on` names in the same table at
 * manifest load, and a name that is already a row joins it" (10
 * §Realtime and caching). The manifest is replaced wholesale — at boot
 * and again whenever the server's `started_at` moves (09 §Wire contract)
 * — so the table is cleared first and rebuilt from what arrived.
 *
 * A panel with no source registers nothing: there is no query to
 * invalidate, and a `custom` element refreshes itself through
 * `window.athanore.subscribe` (09 §Escape hatch).
 */
export function registerPanelRefresh(
  manifest: readonly PluginManifestEntry[],
): void {
  clearRefreshOn()
  for (const entry of manifest) {
    for (const panel of entry.panels ?? []) {
      const names = panel.refresh_on ?? []
      const source = panelSource(panel)
      if (names.length === 0 || source === null) continue
      registerRefreshOn(names, [panelQueryKey(source)])
    }
  }
}

/** {@link registerPanelRefresh}, run whenever the manifest changes. */
export function usePanelRefreshRegistry(
  manifest: readonly PluginManifestEntry[],
): void {
  useEffect(() => {
    registerPanelRefresh(manifest)
  }, [manifest])
}
