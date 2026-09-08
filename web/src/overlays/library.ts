/**
 * What the workflow library overlay is made of, without a DOM
 * (`./Library.tsx`, `docs/v1/10-frontend.md` §Overlays, D35).
 *
 * The left list's rows, which workflow is selected when the overlay
 * opens, the source split into anchored lines, and the one piece of
 * imperative behaviour the viewer has — putting a node's line in view.
 * The component paints these; nothing here knows how any of it looks.
 */
import type { CSSProperties } from 'react'
import type { ThemedToken } from 'shiki'

import type {
  RunSummary,
  SourceNode,
  SourceOut,
  WorkflowOut,
} from '../api/gen/types.gen'

/** shiki's `FontStyle` bits, which is how a themed token carries them. */
const ITALIC = 1
const BOLD = 2
const UNDERLINE = 4
const STRIKETHROUGH = 8

/** One row of the mock's left list: `name · n nodes` over `k runs · file`. */
export type LibraryRow = {
  /** The workflow's name, which is also its key. */
  name: string
  /** How many nodes its finalized graph has. */
  nodes: number
  /**
   * How many runs of it this server holds, or `undefined` when the run
   * list could not be read — which is not the same fact as none, and is
   * not written as one (01 §Real data only).
   */
  runs: number | undefined
  /**
   * The module it is defined in, or `undefined` until
   * `GET /api/workflows/{name}/source` has answered — and for good if it
   * answered 404, which is a workflow whose source Python cannot produce
   * (08 §Workflows). Omitted rather than guessed (01 §Real data only).
   */
  file: string | undefined
}

/**
 * The rows, in the order `GET /api/workflows` sent them — which is by
 * name, and is the one order that does not reshuffle when a run is
 * submitted.
 *
 * The run count is taken from the run list the whole app already shares
 * (10 §Realtime and caching) rather than from a per-workflow request:
 * `GET /api/runs` returns them whole (08 §Conventions), so counting here
 * is counting the same rows the list on the left of the app is drawing.
 */
export function libraryRows(
  workflows: readonly WorkflowOut[],
  runs: readonly RunSummary[] | undefined,
  files: ReadonlyMap<string, string>,
): LibraryRow[] {
  const counts = new Map<string, number>()
  for (const run of runs ?? []) {
    counts.set(run.workflow, (counts.get(run.workflow) ?? 0) + 1)
  }

  return workflows.map((workflow) => ({
    name: workflow.name,
    nodes: Object.keys(workflow.nodes).length,
    runs: runs === undefined ? undefined : (counts.get(workflow.name) ?? 0),
    file: files.get(workflow.name),
  }))
}

/** `1 node`, `8 nodes`: the mock's counts, with the `s` earned. */
export function plural(count: number, noun: string): string {
  return `${String(count)} ${noun}${count === 1 ? '' : 's'}`
}

/**
 * A row's second line: `k runs · file`, with either half dropped when it
 * is not known, and nothing at all when neither is.
 */
export function rowDetail(row: LibraryRow): string | undefined {
  const parts = [
    row.runs === undefined ? undefined : plural(row.runs, 'run'),
    row.file,
  ].filter((part): part is string => part !== undefined)

  return parts.length === 0 ? undefined : parts.join(' · ')
}

/** Which workflow the overlay opens on, and which node it lands on. */
export type Selection = {
  /** The selected workflow's name, or `undefined` with none registered. */
  workflow: string | undefined
  /**
   * The node to scroll to, or `undefined` to open at the top of the
   * file. Only ever a node of {@link Selection.workflow}.
   */
  anchor: string | undefined
}

/**
 * What the overlay opens on, given the selected run's workflow and the
 * node the app has in focus.
 *
 * The selected run's workflow, when this server still has it registered
 * — 10 §Graph pane's `open definition` "opens the library on that
 * workflow", and a run of a workflow this process no longer runs is a
 * real state the run list marks `unregistered` (08 §Runs). Otherwise the
 * first workflow, which is the mock's own default.
 *
 * The anchor comes with the workflow and not on its own: `?node=` names
 * a node of the *selected run's* graph, so it means nothing once the
 * list has fallen back to some other workflow, and it is dropped rather
 * than looked up in a file it was never about.
 */
export function initialSelection(
  workflows: readonly WorkflowOut[],
  runWorkflow: string | undefined,
  node: string | undefined,
): Selection {
  const ofRun = workflows.find((workflow) => workflow.name === runWorkflow)
  if (ofRun !== undefined) return { workflow: ofRun.name, anchor: node }
  return { workflow: workflows[0]?.name, anchor: undefined }
}

/** One line of the viewer: its 1-based number, its text, its anchor. */
export type SourceLine = {
  /** The 1-based line number, as `SourceNode.line` counts them. */
  line: number
  /** The line's text, without its newline. */
  text: string
  /** The node whose body starts here, if one does. */
  node: string | undefined
}

/**
 * `source` as anchored lines.
 *
 * A trailing newline is dropped rather than drawn as a final empty line:
 * every Python module ends in one, and a blank row under the last
 * statement is a line the file does not have.
 *
 * A node whose line is outside the file is left off — the two halves of
 * the response cannot disagree today, but a line number nothing anchors
 * is better than an anchor on the wrong text.
 */
export function sourceLines(
  source: string,
  nodes: Readonly<Record<string, SourceNode>>,
): SourceLine[] {
  const text = source.endsWith('\n') ? source.slice(0, -1) : source
  const lines = text.split('\n')
  const anchors = nodeLines(nodes)

  return lines.map((line, index) => ({
    line: index + 1,
    text: line,
    node: anchors.get(index + 1),
  }))
}

/**
 * The node that starts on each line.
 *
 * Two nodes cannot share a first line, but the wire is a map either way:
 * the lower name wins, so the same response always draws the same
 * anchors.
 */
export function nodeLines(
  nodes: Readonly<Record<string, SourceNode>>,
): Map<number, string> {
  const byLine = new Map<number, string>()
  for (const name of Object.keys(nodes).sort((a, b) => a.localeCompare(b))) {
    const line = nodes[name]?.line
    if (line !== undefined && !byLine.has(line)) byLine.set(line, name)
  }
  return byLine
}

/**
 * The line `node` is defined on in `source`, or `undefined` when it is
 * not defined in this file.
 *
 * A node registered from another module has no line here and is left out
 * of `nodes` by the route rather than given one that points at the wrong
 * text (08 §Workflows); the viewer then opens at the top, which is the
 * honest answer to "show me this definition".
 */
export function anchorLine(
  source: SourceOut | undefined,
  node: string | undefined,
): number | undefined {
  if (source === undefined || node === undefined) return undefined
  return source.nodes[node]?.line
}

/**
 * Put `line` in the middle of `container`, and answer the element that
 * carries it.
 *
 * The element is found by its `data-line`, which is the attribute the
 * viewer hangs on every line whether or not shiki has coloured it yet —
 * so an anchor lands on the same row before and after the highlighter
 * arrives, and a return value of `null` means the source for that line
 * is genuinely not on screen.
 */
export function scrollToLine(
  container: HTMLElement | null,
  line: number | undefined,
): HTMLElement | null {
  if (container === null || line === undefined) return null
  const target = container.querySelector<HTMLElement>(`[data-line="${String(line)}"]`)
  if (target === null) return null
  target.scrollIntoView({ block: 'center' })
  return target
}

/**
 * One shiki token's style: its colour, and the three font flags a
 * TextMate theme can set.
 *
 * The flags are a bitfield on the token — `FontStyle`, an enum shiki
 * does not re-export from its entry point — so they are read here as the
 * bits they are. That is also what keeps this module free of shiki's
 * runtime: nothing it needs from the highlighter is a value.
 */
export function tokenStyle(token: ThemedToken): CSSProperties {
  const style = token.fontStyle ?? 0

  return {
    ...(token.color === undefined ? {} : { color: token.color }),
    ...((style & ITALIC) === 0 ? {} : { fontStyle: 'italic' as const }),
    ...((style & BOLD) === 0 ? {} : { fontWeight: 'bold' as const }),
    ...((style & (UNDERLINE | STRIKETHROUGH)) === 0
      ? {}
      : {
          textDecoration: [
            (style & UNDERLINE) === 0 ? '' : 'underline',
            (style & STRIKETHROUGH) === 0 ? '' : 'line-through',
          ]
            .filter((part) => part !== '')
            .join(' '),
        }),
  }
}
