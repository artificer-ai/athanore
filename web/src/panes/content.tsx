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
 *   is sufficient". The overview has a renderer of its own only because
 *   its route sends a fourth key the `dashboard` kind does not declare
 *   (`meta`, 15 D140); {@link BUILTIN_RENDERERS} is that one exception,
 *   and it is keyed by the panel's name on `_builtin` alone.
 */
import type { ReactNode } from 'react'

import {
  ChartPane,
  DashboardPane,
  ErrorCard,
  KvPane,
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
 * The builtin panels whose data the `kind` alone does not describe.
 *
 * One entry: `overview`, whose route answers with a `dashboard` plus the
 * `meta` grid 10 §Panes puts between the tiles and the NODES table. Any
 * other server's panel named `overview` is not this one — the key is the
 * name *on `_builtin`* — and a build talking to a server that dropped
 * `meta` still draws the three keys the kind declares, because
 * {@link asOverview} narrows a missing `meta` to an empty grid rather
 * than to a mismatch.
 */
const BUILTIN_RENDERERS: Record<
  string,
  (data: unknown, ctx: RenderContext) => Content | null
> = {
  overview: (data, ctx) => {
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
    if (builtin !== undefined) return builtin(data, ctx) ?? mismatch
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
