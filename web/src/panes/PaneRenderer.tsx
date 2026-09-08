/**
 * One pane, drawn from its manifest entry and the data its `source`
 * answered with (`docs/v1/09-plugins.md` §Panel kinds,
 * `docs/v1/10-frontend.md` §Plugin renderers).
 *
 * This is the component that makes the plugin system visible: the host
 * knows a panel's `kind`, its `source` and its scope, and nothing else
 * about it. Everything below the pane bar came off the wire.
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
 *   render here through exactly the path a plugin's would, which is what
 *   09 §Builtins are plugins means by "the proof the API is sufficient".
 *   T063a and T063b give those two panes renderers of their own; until
 *   they do, this is what draws them.
 */
import type { ReactNode } from 'react'

import { BUILTIN_WORKFLOW } from './manifest'
import {
  ChartPane,
  DashboardPane,
  ErrorCard,
  KvPane,
  LogPane,
  MarkdownPane,
  PaneSection,
  PlaceholderCard,
  TablePane,
  asChart,
  asDashboard,
  asKv,
  asLog,
  asMarkdown,
  asTable,
} from './kinds'
import {
  DATA_KINDS,
  PanelSourceError,
  panelParams,
  usePanelSource,
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
 * that never ends. Every other kind is poured into the pane's.
 */
type Content = { node: ReactNode; scrolls: boolean }

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

/** The pane's own header: what it is, and where its data comes from. */
function PaneHeader({ pane }: { pane: Pane }) {
  return (
    <div className="text-hint flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-900)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
      {!pane.builtin && (
        <>
          <span className="text-[var(--color-accent-300)]">PLUGIN</span>
          <span className="text-[var(--color-neutral-800)]">│</span>
        </>
      )}
      <span data-testid="pane-title" className="text-[var(--color-neutral-400)]">
        {pane.name}
      </span>
      <div className="flex-1" />
      {pane.panel.source != null && (
        <span data-testid="pane-source" className="whitespace-nowrap">
          {pane.panel.source}
        </span>
      )}
    </div>
  )
}

/** 10 §Panes' footer line, on the panes a workflow contributed. */
function PaneFooter({ workflow }: { workflow: string }) {
  return (
    <p className="text-kicker flex-none px-[14px] pb-[16px] normal-case text-muted-foreground">
      registered by {workflow} · panes are contributed with @wf.panel(...)
    </p>
  )
}

/** A status line: pending, or a scope that is not resolved yet. */
function Status({ children }: { children: ReactNode }) {
  return (
    <p className="text-row text-muted-foreground" role="status">
      {children}
    </p>
  )
}

/**
 * The renderer for `pane`'s kind over `data`, or the card that says why
 * there is none.
 *
 * A plain function rather than a component: what it decides — whether
 * the kind brings its own scroller — is a fact about the element it
 * returns, and a component could only report it by rendering it.
 */
function renderKind(pane: Pane, data: unknown): Content {
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
type PanelQuery = {
  isPending: boolean
  isError: boolean
  error: unknown
  data: unknown
}

/**
 * The pane's body: its data, or the one thing standing between the pane
 * and its data, in the order those things happen.
 */
function paneContent(pane: Pane, params: PanelParams | null, query: PanelQuery): Content {
  // `custom`, `form` and anything this build does not know are drawn
  // from the manifest entry alone.
  if (!DATA_KINDS.has(pane.panel.kind)) return renderKind(pane, undefined)

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

  if (params === null) return { node: <Status>{waitingFor(pane)}</Status>, scrolls: false }
  if (query.isPending) {
    return { node: <Status>loading {pane.name}…</Status>, scrolls: false }
  }
  if (query.isError) {
    return { node: sourceError(query.error, pane.panel.source), scrolls: false }
  }
  return renderKind(pane, query.data)
}

export function PaneRenderer({ pane, scope }: { pane: Pane; scope: PanelScope }) {
  const params = panelParams(pane.panel, scope)
  const query = usePanelSource(pane.panel, params)

  const content = paneContent(pane, params, query)

  const footer = pane.builtin ? null : <PaneFooter workflow={pane.workflow} />

  return (
    <div
      data-testid="pane-renderer"
      data-kind={pane.panel.kind}
      className="flex min-h-0 flex-1 flex-col"
    >
      <PaneHeader pane={pane} />
      {content.scrolls ? (
        <>
          {content.node}
          {footer}
        </>
      ) : (
        <div className="min-h-0 flex-1 overflow-x-hidden overflow-y-auto">
          <PaneSection>{content.node}</PaneSection>
          {footer}
        </div>
      )}
    </div>
  )
}
