/**
 * The invalidation table: what one event makes stale, and how much of
 * it a burst is allowed to refetch.
 *
 * Freshness in this app comes from events, never from a clock: nothing
 * polls, and a view that goes stale is a row missing from the table
 * below rather than an interval somebody forgot to set. Three things
 * make that affordable:
 *
 * - **exact before glob.** `task.stream` arrives two or three times a
 *   second per streaming task and matches `task.*` on a plain prefix
 *   test; if it ever reached that row, every chunk of every transcript
 *   would refetch the run, the graph and the task. An exact name wins
 *   outright and no glob is consulted.
 * - **the transcript appends.** `task.stream` names the chunks that
 *   arrived (18); {@link Invalidator.appendStream} fetches exactly those
 *   and merges them into the cache, so following a live agent costs one
 *   small page per event rather than the whole transcript.
 * - **coalescing.** Keys are collected for {@link COALESCE_WINDOW_MS}
 *   and invalidated once each, so the ten events a fanning-out node
 *   emits in one tick produce one refetch per resource.
 *
 * The keys themselves are the generated ones (D49): every entry here is
 * built by an `@hey-api` `*QueryKey` helper from the same options the
 * query used, so the table cannot drift from what the components ask
 * for. Each is built with its path parameters and nothing else, which
 * is what makes it a *prefix*: TanStack matches a filter key partially,
 * so `stream(4)` reaches every page of task 4's transcript whatever
 * `after` it was fetched with.
 */
import type { QueryClient, QueryKey } from '@tanstack/react-query'

import {
  getGraphApiRunsRunIdGraphGetQueryKey,
  getLogApiRunsRunIdLogGetQueryKey,
  getRequestsApiRunsRunIdRequestsGetQueryKey,
  getRunApiRunsRunIdGetQueryKey,
  getStreamApiTasksTaskIdStreamGetQueryKey,
  getSourceApiWorkflowsNameSourceGetQueryKey,
  getTaskApiTasksTaskIdGetQueryKey,
  getWorkflowApiWorkflowsNameGetQueryKey,
  listRequestsApiRequestsGetQueryKey,
  listRunsApiRunsGetQueryKey,
  listWorkflowsApiWorkflowsGetQueryKey,
  manifestApiPluginsGetQueryKey,
} from '../api/gen/@tanstack/react-query.gen'
import { getStreamApiTasksTaskIdStreamGet } from '../api/gen/sdk.gen'
import type {
  GetEventsApiRunsRunIdEventsGetResponse,
  StreamOut,
  TaskStream,
} from '../api/gen/types.gen'

/**
 * One event off the feed.
 *
 * Derived from the generated envelope union rather than described again
 * here, so a payload the server adds or renames reaches this file as a
 * failed typecheck (02 §One wire contract).
 */
export type AthanoreEvent = GetEventsApiRunsRunIdEventsGetResponse[number]

/** How long keys are collected before they are invalidated (10). */
export const COALESCE_WINDOW_MS = 250

/**
 * A generated key with its `path` taken off: the prefix over every
 * name of a name-keyed resource.
 *
 * The two workflow helpers below type `path` as required, so there is
 * no generated spelling of "the source of *any* workflow". The key they
 * build is `[{ _id, baseUrl, path: { name } }]`, and TanStack's partial
 * matching is deep over objects, so `[{ _id, baseUrl }]` reaches every
 * one of them — the prefix property D155 gives the run keys, one
 * parameter further up. `_id` and `baseUrl` stay the generator's rather
 * than being written here (D49, D253).
 */
function withoutPath(key: QueryKey): QueryKey {
  const [head, ...rest] = key
  if (typeof head !== 'object' || head === null) return key
  const prefix: Record<string, unknown> = { ...(head as Record<string, unknown>) }
  delete prefix.path
  return [prefix, ...rest]
}

/**
 * The twelve cache entries the table names, each as the generated key
 * of the query that fills it.
 */
export const queryKeys = {
  /** `GET /api/runs` — the run list and the header's counts. */
  runs: (): QueryKey => listRunsApiRunsGetQueryKey(),
  /** `GET /api/runs/{id}` — the overview pane. */
  run: (runId: string): QueryKey =>
    getRunApiRunsRunIdGetQueryKey({ path: { run_id: runId } }),
  /** `GET /api/runs/{id}/graph` — the graph pane. */
  graph: (runId: string): QueryKey =>
    getGraphApiRunsRunIdGraphGetQueryKey({ path: { run_id: runId } }),
  /** `GET /api/runs/{id}/log` — the log pane. */
  log: (runId: string): QueryKey =>
    getLogApiRunsRunIdLogGetQueryKey({ path: { run_id: runId } }),
  /** `GET /api/runs/{id}/requests` — the requests pane. */
  requests: (runId: string): QueryKey =>
    getRequestsApiRunsRunIdRequestsGetQueryKey({ path: { run_id: runId } }),
  /** `GET /api/requests` — the inbox, the requests pane's global twin. */
  inbox: (): QueryKey => listRequestsApiRequestsGetQueryKey(),
  /** `GET /api/tasks/{id}` — one attempt, in the task drawer. */
  task: (taskId: number): QueryKey =>
    getTaskApiTasksTaskIdGetQueryKey({ path: { task_id: taskId } }),
  /** `GET /api/tasks/{id}/stream` — the agent pane's transcript. */
  stream: (taskId: number): QueryKey =>
    getStreamApiTasksTaskIdStreamGetQueryKey({ path: { task_id: taskId } }),
  /** `GET /api/workflows` — the library's list and the new-run chips. */
  workflows: (): QueryKey => listWorkflowsApiWorkflowsGetQueryKey(),
  /** `GET /api/workflows/{name}`, for every name (`withoutPath`). */
  workflow: (): QueryKey =>
    withoutPath(getWorkflowApiWorkflowsNameGetQueryKey({ path: { name: '' } })),
  /** `GET /api/workflows/{name}/source`, for every name: the viewer. */
  source: (): QueryKey =>
    withoutPath(getSourceApiWorkflowsNameSourceGetQueryKey({ path: { name: '' } })),
  /** `GET /api/plugins` — the pane cycle, the cards, the palette's rows. */
  manifest: (): QueryKey => manifestApiPluginsGetQueryKey(),
} as const

/** What one event name makes stale. */
export type Invalidation = (event: AthanoreEvent) => QueryKey[]

/**
 * 10 §Realtime's table, transcribed.
 *
 * Four readings of that section are worth naming, because none of them
 * is visible in the row alone:
 *
 * - `task.stream`'s key is here so that the matcher can be *asked* about
 *   it and answer with the transcript rather than with `task.*`'s three
 *   refetches. It is never invalidated: {@link Invalidator.handle} sends
 *   the name to {@link Invalidator.appendStream} instead, which is the
 *   row's own comment ("fetch after=seq, append").
 * - `task.*` carries `runs` although the table's row does not, because
 *   the sentence under the table does: "the header's active count and
 *   the run list come from `GET /api/runs`, refetched on
 *   `run.*`/`task.*`". A run list whose NODE and STATUS cells only moved
 *   on `run.*` would sit frozen for the whole of a long run (D155).
 * - `request.*` carries `runs` and `run` for the same reason, and it is
 *   the one the table missed: `GET /api/runs` answers with
 *   `pending_requests`, which is what draws the `⚠` on a row. A request
 *   opens while its task is still `in_progress` — a permission mid-turn
 *   never parks the task — so no `task.*` follows it, and a list
 *   refetched only on the other two shows nothing waiting on the
 *   operator until something unrelated moves (D208).
 * - `workflow.*` is 22 §SPA's row: a registration, a reload or a
 *   removal makes the workflow list, the single-workflow and source
 *   queries and the manifest stale, and that one refetch is what moves
 *   the library, the new-run chips, the palette's plugin rows and the
 *   pane cycle. `runs` is in it for D208's reason one more time:
 *   `GET /api/runs` answers `unregistered` per request from the live
 *   registry (08 §Runs), and a removal writes no run or task status and
 *   emits no `run.*`/`task.*` (22 §Remove), so a list refetched only on
 *   those would draw the row's `⊘` only when something unrelated moved
 *   (D253). The name-keyed prefixes reach every workflow at once; the
 *   event names one, but the list and the chips are about all of them.
 */
export const invalidations: Record<string, Invalidation> = {
  'task.stream': (e) => (e.task_id == null ? [] : [queryKeys.stream(e.task_id)]),
  'run.*': (e) => [
    queryKeys.runs(),
    ...(e.run_id == null ? [] : [queryKeys.run(e.run_id), queryKeys.graph(e.run_id)]),
  ],
  'task.*': (e) => [
    queryKeys.runs(),
    ...(e.run_id == null ? [] : [queryKeys.run(e.run_id), queryKeys.graph(e.run_id)]),
    ...(e.task_id == null ? [] : [queryKeys.task(e.task_id)]),
  ],
  'log.appended': (e) => (e.run_id == null ? [] : [queryKeys.log(e.run_id)]),
  'request.*': (e) => [
    queryKeys.runs(),
    ...(e.run_id == null
      ? []
      : [queryKeys.run(e.run_id), queryKeys.requests(e.run_id)]),
    queryKeys.inbox(),
  ],
  'agent.stats': (e) => (e.run_id == null ? [] : [queryKeys.run(e.run_id)]),
  'workflow.*': () => [
    queryKeys.workflows(),
    queryKeys.workflow(),
    queryKeys.source(),
    queryKeys.manifest(),
    queryKeys.runs(),
  ],
  'plugin.*': (e) => panelsRefreshingOn(e.name),
}

/* -------------------------------------------------------------------- */
/* Plugin panels                                                         */
/* -------------------------------------------------------------------- */

/** Event name → the keys the panels watching it want refetched. */
const refreshOn = new Map<string, QueryKey[]>()
const refreshOnListeners = new Set<(names: readonly string[]) => void>()

/**
 * Register a plugin panel's `refresh_on` names against the keys its
 * pane reads (09 §Wire contract).
 *
 * "Plugin panels register their `refresh_on` names in the same table at
 * manifest load" (10), so a name here joins whatever row it already
 * matches rather than replacing it: a panel refreshing on `log.appended`
 * refetches beside the log pane, and one refreshing on a name the
 * `plugin.*` row is the only match for refetches alone.
 *
 * The manifest is replaced wholesale — at boot and again whenever the
 * server's `started_at` changes (09) — so {@link clearRefreshOn} is how
 * a reload starts from a clean table.
 *
 * A name may be a glob. {@link panelsRefreshingOn} matches it as one;
 * the feed, which has no wildcard to subscribe with, registers a
 * listener for the literal name and never hears a frame by it — which
 * costs nothing, because every glob a builtin or a plugin writes is over
 * the vocabulary the feed already listens to in full (`sse.ts`).
 */
export function registerRefreshOn(
  names: readonly string[],
  keys: readonly QueryKey[],
): void {
  for (const name of names) {
    refreshOn.set(name, dedupeKeys([...(refreshOn.get(name) ?? []), ...keys]))
  }
  const registered = [...refreshOn.keys()]
  for (const listener of refreshOnListeners) listener(registered)
}

/** Forget every registration; a manifest reload calls this first. */
export function clearRefreshOn(): void {
  refreshOn.clear()
}

/**
 * The keys registered against `name` exactly, ignoring the globs.
 *
 * What {@link Invalidator.handle} uses for `task.stream`, and the only
 * place the distinction matters: a panel refreshing on `task.*` must not
 * be refetched two or three times a second per streaming task, which is
 * the same reason the table's own `task.*` row is never reached for that
 * name (10 §Realtime and caching). A panel that genuinely wants the
 * stream's rate says `task.stream` and gets it.
 */
function exactlyRefreshingOn(name: string): QueryKey[] {
  return refreshOn.get(name) ?? []
}

/**
 * The keys the panels watching `name` want refetched.
 *
 * `refresh_on` is a list of event-name **globs** (09 §Wire contract), so
 * a panel that registered `task.*` is matched by `task.done` — the same
 * first-exact-then-glob matching the table itself uses, over the panels'
 * registrations rather than over its own rows. An exact registration is
 * not exclusive here as a table row is: two panels may watch one event
 * by different spellings, and both of them meant it.
 */
export function panelsRefreshingOn(name: string): QueryKey[] {
  const globbed = [...refreshOn.entries()]
    .filter(([pattern]) => pattern.includes('*') && globMatches(pattern, name))
    .flatMap(([, keys]) => keys)
  return dedupeKeys([...exactlyRefreshingOn(name), ...globbed])
}

/**
 * Be told which names are registered, now and on every registration.
 *
 * The feed listens to this: a browser's `EventSource` delivers a named
 * frame only to a listener for that name, and a plugin's own event names
 * are not known until its manifest has been read (`sse.ts`).
 */
export function subscribeRefreshOn(
  listener: (names: readonly string[]) => void,
): () => void {
  refreshOnListeners.add(listener)
  listener([...refreshOn.keys()])
  return () => {
    refreshOnListeners.delete(listener)
  }
}

/* -------------------------------------------------------------------- */
/* The matcher                                                           */
/* -------------------------------------------------------------------- */

const globs = new Map<string, RegExp>()

/**
 * Does `name` match `pattern`, read as an event-name glob?
 *
 * The one matcher: the table's rows, a panel's `refresh_on` and a
 * plugin element's `window.athanore.subscribe` names are all globs over
 * the same vocabulary (09 §Wire contract), and three spellings of
 * "matches" would be three chances for `task.*` to mean three things.
 */
export function eventNameMatches(pattern: string, name: string): boolean {
  return globMatches(pattern, name)
}

function globMatches(pattern: string, name: string): boolean {
  let matcher = globs.get(pattern)
  if (matcher === undefined) {
    const literals = pattern.split('*').map((part) => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
    matcher = new RegExp(`^${literals.join('.*')}$`)
    globs.set(pattern, matcher)
  }
  return matcher.test(name)
}

/** `JSON.stringify` of a key: what makes two keys the same key here. */
function serializeKey(key: QueryKey): string {
  return JSON.stringify(key)
}

function dedupeKeys(keys: readonly QueryKey[]): QueryKey[] {
  const byValue = new Map<string, QueryKey>()
  for (const key of keys) byValue.set(serializeKey(key), key)
  return [...byValue.values()]
}

/**
 * What `event` makes stale: the table's row for it, first-exact-then-glob,
 * plus whatever plugin panels asked to be refreshed on that name.
 *
 * An exact row wins outright — no glob is consulted once one matched —
 * which is the whole of `task.stream` never reaching `task.*`.
 */
export function keysFor(event: AthanoreEvent): QueryKey[] {
  const exact = Object.hasOwn(invalidations, event.name)
    ? invalidations[event.name]
    : undefined
  const matched = exact
    ? [exact]
    : Object.entries(invalidations)
        .filter(([pattern]) => pattern.includes('*') && globMatches(pattern, event.name))
        .map(([, invalidation]) => invalidation)

  return dedupeKeys([
    ...matched.flatMap((invalidation) => invalidation(event)),
    ...panelsRefreshingOn(event.name),
  ])
}

/* -------------------------------------------------------------------- */
/* The coalescer                                                         */
/* -------------------------------------------------------------------- */

function isStreamOut(data: unknown): data is StreamOut {
  if (typeof data !== 'object' || data === null) return false
  const page = data as Partial<StreamOut>
  return Array.isArray(page.chunks) && typeof page.last_seq === 'number'
}

function isTaskStream(data: unknown): data is TaskStream {
  if (typeof data !== 'object' || data === null) return false
  return typeof (data as Partial<TaskStream>).seq_from === 'number'
}

/** The highest sequence a cached page actually holds. */
function heldSeq(page: StreamOut): number {
  return page.chunks.reduce((highest, chunk) => Math.max(highest, chunk.seq), 0)
}

/** Merge a fetched page into a cached one, keeping sequence order. */
function mergeStream(current: StreamOut, page: StreamOut): StreamOut {
  const held = new Set(current.chunks.map((chunk) => chunk.seq))
  const added = page.chunks.filter((chunk) => !held.has(chunk.seq))
  if (
    added.length === 0 &&
    page.last_seq === current.last_seq &&
    page.live === current.live
  ) {
    // Nothing new: the same object, so nothing re-renders.
    return current
  }
  return {
    chunks: [...current.chunks, ...added].sort((a, b) => a.seq - b.seq),
    last_seq: Math.max(current.last_seq, page.last_seq),
    live: page.live,
  }
}

/**
 * The end of the feed that touches the cache: it turns an event into
 * invalidations, batches them, and appends transcripts.
 *
 * One per {@link EventFeed}; a test may drive one on its own.
 */
export class Invalidator {
  readonly #queryClient: QueryClient
  readonly #windowMs: number
  readonly #pending = new Map<string, QueryKey>()
  #timer: ReturnType<typeof setTimeout> | null = null

  constructor(queryClient: QueryClient, windowMs: number = COALESCE_WINDOW_MS) {
    this.#queryClient = queryClient
    this.#windowMs = windowMs
  }

  /** Apply one event. */
  handle(event: AthanoreEvent): void {
    if (event.name === 'task.stream') {
      if (event.task_id != null && isTaskStream(event.data)) {
        void this.appendStream(event.task_id, event.data.seq_from)
      }
      // The transcript appends; anything else watching the name is a
      // plugin panel that named `task.stream` outright, and it still
      // gets its refetch. A panel's `task.*` deliberately does not
      // match here — see `exactlyRefreshingOn`.
      for (const key of exactlyRefreshingOn(event.name)) this.enqueue(key)
      return
    }

    for (const key of keysFor(event)) this.enqueue(key)
  }

  /** Mark one key stale, at the end of the current window. */
  enqueue(key: QueryKey): void {
    this.#pending.set(serializeKey(key), key)
    this.#timer ??= setTimeout(() => {
      this.flush()
    }, this.#windowMs)
  }

  /** Invalidate everything collected so far, once per distinct key. */
  flush(): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer)
      this.#timer = null
    }
    const keys = [...this.#pending.values()]
    this.#pending.clear()
    for (const queryKey of keys) void this.#queryClient.invalidateQueries({ queryKey })
  }

  /** Drop what is pending without invalidating it. */
  dispose(): void {
    if (this.#timer !== null) {
      clearTimeout(this.#timer)
      this.#timer = null
    }
    this.#pending.clear()
  }

  /**
   * Fetch the chunks a `task.stream` event announced and append them to
   * the cached transcript, rather than refetching it.
   *
   * `seqFrom` says where the event's new chunks begin and the cache says
   * where ours end; we ask for everything after the earlier of the two.
   * That is `seqFrom - 1` when a viewer is exactly caught up, and
   * further back when a frame was missed — so a hole fills itself
   * instead of persisting behind a cursor that ran ahead of the data.
   *
   * Nothing is fetched when no viewer holds the transcript: whoever
   * opens it next fetches it whole. A page that cannot be merged — an
   * infinite query, say — is marked stale instead, which is slower and
   * still correct.
   */
  async appendStream(taskId: number, seqFrom: number): Promise<void> {
    const streamKey = queryKeys.stream(taskId)
    const cached = this.#queryClient.getQueriesData<unknown>({ queryKey: streamKey })
    const pages: [QueryKey, StreamOut][] = []
    let unmergeable = false
    for (const [key, data] of cached) {
      if (isStreamOut(data)) pages.push([key, data])
      else if (data !== undefined) unmergeable = true
    }

    if (pages.length === 0) {
      if (unmergeable) this.enqueue(streamKey)
      return
    }

    const after = Math.min(...pages.map(([, page]) => heldSeq(page)), seqFrom - 1)

    let fetched: StreamOut
    try {
      const result = await getStreamApiTasksTaskIdStreamGet({
        path: { task_id: taskId },
        query: { after },
      })
      if (result.data === undefined) {
        // The server refused or the connection failed. The transcript is
        // stale rather than wrong, so say so and let the view refetch.
        this.enqueue(streamKey)
        return
      }
      fetched = result.data
    } catch {
      this.enqueue(streamKey)
      return
    }

    for (const [key] of pages) {
      this.#queryClient.setQueryData<StreamOut>(key, (current) =>
        current === undefined ? current : mergeStream(current, fetched),
      )
    }
  }
}
