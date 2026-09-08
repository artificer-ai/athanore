/**
 * What a panel draws: the kind dispatch, the states in which there is
 * nothing to draw yet, and the cards appended to the overview
 * (`docs/v1/09-plugins.md` §Panel kinds, `docs/v1/10-frontend.md`
 * §Plugin renderers).
 *
 * Separate from `./PaneRenderer.tsx` because two things reach for it now
 * — a pane, and a `placement="card"` panel below the overview
 * (`./PanelCards.tsx`, 09 §Slots) — and a panel must draw the same way
 * in both. The renderer around it differs (a pane has the bar's header,
 * a card has a frame); the dispatch does not.
 *
 * Nothing here is a component. Every helper returns an element rather
 * than being one, which is what lets the module export functions at all
 * (`.oxlintrc.json`, `react/only-export-components`) — and it is also
 * what {@link Content} needs, since whether a kind brings its own
 * scroller is a fact about the element, not something a component could
 * report without rendering first.
 *
 * Four things it will not do:
 *
 * - **it does not throw.** A kind this build has no renderer for is a
 *   placeholder card (09: "Unknown `kind` renders a placeholder card,
 *   never a crash"), and so is a declared kind whose data does not match
 *   the shape 09 gives it. A plugin built against a later Athanore
 *   degrades; it does not white-screen the app.
 * - **it does not hide a refusal.** A `source` that answered 500 draws
 *   an error card with the status, the code and the URL — the plugin's
 *   failure, said plainly, rather than an empty pane the operator has to
 *   diagnose from the network tab.
 * - **it does not ask for what it cannot ask for.** A panel whose scope
 *   is not resolved yet — a `run` panel with no run selected — says what
 *   it is waiting for instead of spending a request on a 404 (09
 *   §Context and scopes).
 * - **it does not special-case the builtins.** The overview and the log
 *   are `dashboard` and `log` panels of the `_builtin` workflow and
 *   reach their renderers through exactly the path a plugin's would,
 *   which is what 09 §Builtins are plugins means by "the proof the API
 *   is sufficient". Each has a renderer of its own only for what 09's
 *   kind does not cover — the overview's route sends a fourth key
 *   (`meta`, 15 D140), and the log pane is asked for a composer, a
 *   filter and markdown that a plugin's list of lines is not (10 §Panes
 *   item 2). {@link BUILTIN_RENDERERS} is the whole of that, and it is
 *   keyed by the panel's name on `_builtin` alone.
 */
import type { ReactNode } from 'react'

import {
  ChartPane,
  DashboardPane,
  ErrorCard,
  KvPane,
  Log,
  LogPane,
  MarkdownPane,
  Overview,
  PlaceholderCard,
  TablePane,
  asChart,
  asDashboard,
  asKv,
  asLog,
  asMarkdown,
  asOverview,
  asTable,
} from './kinds'
import { BUILTIN_WORKFLOW } from './manifest'
import {
  DATA_KINDS,
  PanelSourceError,
  type PanelParams,
  type PanelScope,
} from './source'
import type { Pane } from './usePanes'

/**
 * What to draw, and whether it brings its own scroller.
 *
 * `log` does: it virtualises, so it needs a viewport with a height
 * rather than one that grows with its content, and nesting it inside the
 * pane's own scroller would leave the virtualiser measuring a viewport
 * that never ends. The overview does too, because its sections are
 * full-bleed strips divided by rules rather than a padded column. Every
 * other kind is poured into the pane's.
 */
export type Content = { node: ReactNode; scrolls: boolean }

/** What the panel is being drawn for, beyond its own data. */
export type RenderContext = {
  /** The ids the panel's route is asked with (09 §Context and scopes). */
  scope: PanelScope
  /** Open an attempt in the task drawer (10 §Overlays). */
  onOpenTask?: ((taskId: number) => void) | undefined
  /**
   * `?node=`: the node the event log is filtered to (10 §Panes item 2).
   *
   * A filter and not a scope: it narrows what one pane *draws* and is
   * deliberately not in {@link PanelScope}, which is what a panel's
   * route is asked with. Filtering server-side would be a second cache
   * entry per node of a resource the pane already has whole.
   */
  node?: string | undefined
  /** Write `?node=`; the log pane's filter clears itself with it. */
  onFilterNode?: ((node: string | undefined) => void) | undefined
  /**
   * The `placement="card"` panels of the run in scope, ready to mount
   * (`./PanelCards.tsx`).
   *
   * The host makes them and the overview places them, because a card is
   * a panel of any kind: drawing one means reaching back into
   * {@link renderKind}, and a renderer that made its own cards would be
   * imported by the module that draws them.
   */
  cards?: ReactNode
}

/** What a panel is waiting for, when its scope is not resolved. */
function waitingFor(pane: Pane): string {
  switch (pane.panel.scope) {
    case 'run':
      return 'select a run to load this panel'
    case 'task':
      return 'select a task to load this panel'
    case 'node':
      return 'this panel follows a node its run has not named'
    default:
      return 'this panel has no scope to load in'
  }
}

/** A status line: pending, or a scope that is not resolved yet. */
function statusLine(text: ReactNode): ReactNode {
  return (
    <p className="text-row text-muted-foreground" role="status">
      {text}
    </p>
  )
}

/**
 * The builtin panels the `kind` alone does not describe, keyed by their
 * name *on `_builtin`*: another server's panel of the same name is not
 * this one, and reaches its kind's renderer like any plugin's.
 *
 * Two of them, and neither is a special case of the host — both are
 * declared through the plugin API and fetched through it (09 §Builtins
 * are plugins). What they add is what their route sends beyond the kind,
 * or what 10 §Panes asks of that one pane and of no other:
 *
 * - **`overview`** answers with a `dashboard` plus the `meta` grid 10
 *   puts between the tiles and the NODES table. A build talking to a
 *   server that dropped `meta` still draws the three keys the kind
 *   declares, because {@link asOverview} narrows a missing `meta` to an
 *   empty grid rather than to a mismatch.
 * - **`log`** answers with the `log` kind's own rows, and 10 §Panes item
 *   2 gives that pane a header, a `?node=` filter, markdown for what an
 *   agent or a person wrote, and the composer an operator appends a note
 *   with. A plugin's `log` panel has none of those: it is a list of
 *   lines, which is what the kind promises.
 */
const BUILTIN_RENDERERS: Record<
  string,
  (pane: Pane, data: unknown, ctx: RenderContext) => Content | null
> = {
  overview: (_pane, data, ctx) => {
    const overview = asOverview(data)
    if (overview === null) return null
    return {
      scrolls: true,
      node: (
        <Overview
          data={overview}
          runId={ctx.scope.runId}
          onOpenTask={ctx.onOpenTask}
          cards={ctx.cards}
        />
      ),
    }
  },

  log: (pane, data, ctx) => {
    const rows = asLog(data)
    if (rows === null) return null
    return {
      scrolls: true,
      node: (
        <Log
          data={rows}
          runId={ctx.scope.runId}
          {...(pane.panel.source == null ? {} : { source: pane.panel.source })}
          {...(ctx.node === undefined ? {} : { node: ctx.node })}
          {...(ctx.onFilterNode === undefined ? {} : { onFilterNode: ctx.onFilterNode })}
        />
      ),
    }
  },
}

/**
 * The renderer for `pane`'s kind over `data`, or the card that says why
 * there is none.
 *
 * A plain function rather than a component: what it decides — whether
 * the kind brings its own scroller — is a fact about the element it
 * returns, and a component could only report it by rendering it.
 */
export function renderKind(pane: Pane, data: unknown, ctx: RenderContext): Content {
  const kind: string = pane.panel.kind
  const source = pane.panel.source ?? undefined

  /** The data did not match the shape 09 gives this kind. */
  const mismatch: Content = {
    scrolls: false,
    node: (
      <ErrorCard
        message={`this panel's source did not answer with the shape a ${kind} panel needs`}
        {...(source === undefined ? {} : { source })}
      />
    ),
  }

  if (pane.workflow === BUILTIN_WORKFLOW) {
    const builtin = BUILTIN_RENDERERS[pane.name]
    if (builtin !== undefined) return builtin(pane, data, ctx) ?? mismatch
  }

  switch (kind) {
    case 'markdown': {
      const text = asMarkdown(data)
      return text === null
        ? mismatch
        : { node: <MarkdownPane text={text} />, scrolls: false }
    }
    case 'kv': {
      const kv = asKv(data)
      return kv === null ? mismatch : { node: <KvPane data={kv} />, scrolls: false }
    }
    case 'table': {
      const table = asTable(data)
      return table === null
        ? mismatch
        : { node: <TablePane data={table} label={pane.name} />, scrolls: false }
    }
    case 'log': {
      const rows = asLog(data)
      return rows === null ? mismatch : { node: <LogPane rows={rows} />, scrolls: true }
    }
    case 'chart': {
      const chart = asChart(data)
      return chart === null
        ? mismatch
        : { node: <ChartPane data={chart} />, scrolls: false }
    }
    case 'dashboard': {
      const dashboard = asDashboard(data)
      return dashboard === null
        ? mismatch
        : { node: <DashboardPane data={dashboard} />, scrolls: false }
    }
    case 'form':
      return {
        scrolls: false,
        node: (
          <PlaceholderCard
            title="this panel is an action form"
            detail={
              source === undefined
                ? 'the form renderer is not built yet'
                : `action ${source} · the form renderer is not built yet`
            }
          />
        ),
      }
    case 'custom':
      return {
        scrolls: false,
        node: (
          <PlaceholderCard
            title="this panel is a plugin element"
            detail={
              pane.panel.element == null
                ? 'plugin elements are not mounted yet'
                : `<${pane.panel.element}> · plugin elements are not mounted yet`
            }
          />
        ),
      }
    default:
      return {
        scrolls: false,
        node: (
          <PlaceholderCard
            title={`this build has no renderer for a ${kind} panel`}
            detail={
              pane.workflow === BUILTIN_WORKFLOW
                ? 'declared by the core'
                : `declared by ${pane.workflow}, a plugin of this server`
            }
          />
        ),
      }
  }
}

/** The error a failed `source` renders as, with whatever it said. */
function sourceError(error: unknown, source: string | null | undefined): ReactNode {
  const known = error instanceof PanelSourceError ? error : null
  return (
    <ErrorCard
      message={error instanceof Error ? error.message : 'the request failed'}
      {...(known?.status === undefined ? {} : { status: known.status })}
      {...(known?.code === undefined ? {} : { code: known.code })}
      {...(source == null ? {} : { source })}
    />
  )
}

/** As much of `useQuery`'s result as the pane's states are decided by. */
export type PanelQuery = {
  isPending: boolean
  isError: boolean
  error: unknown
  data: unknown
}

/**
 * The panel's body: its data, or the one thing standing between the
 * panel and its data, in the order those things happen.
 */
export function paneContent(
  pane: Pane,
  params: PanelParams | null,
  query: PanelQuery,
  ctx: RenderContext,
): Content {
  // `custom`, `form` and anything this build does not know are drawn
  // from the manifest entry alone.
  if (!DATA_KINDS.has(pane.panel.kind)) return renderKind(pane, undefined, ctx)

  if (pane.panel.source == null) {
    // Registration refuses a data panel with no source (09 §Registration
    // and validation, rule 4), so this is a server that is not the one
    // this build was written for.
    return {
      scrolls: false,
      node: (
        <PlaceholderCard
          title={`this ${pane.panel.kind} panel declares no source`}
          detail={`registered by ${pane.workflow}`}
        />
      ),
    }
  }

  if (params === null) return { node: statusLine(waitingFor(pane)), scrolls: false }
  if (query.isPending) {
    return { node: statusLine(`loading ${pane.name}…`), scrolls: false }
  }
  if (query.isError) {
    return { node: sourceError(query.error, pane.panel.source), scrolls: false }
  }
  return renderKind(pane, query.data, ctx)
}
