/**
 * The workflow library's model (`overlays/library.ts`): the left list's
 * rows, what the overlay opens on, the source split into anchored lines,
 * and the scroll that lands on one of them.
 *
 * All of it without a component, because none of it is about how the
 * panel looks: a run count that zero-fills a list nobody could read and
 * an anchor that follows the operator onto another workflow's file are
 * both bugs a rendered test would have to go looking for.
 */
import type { ThemedToken } from 'shiki'
import { describe, expect, it, vi } from 'vitest'

import type { RunSummary, SourceOut, WorkflowOut } from '../../api/gen/types.gen'
import {
  anchorLine,
  initialSelection,
  libraryRows,
  nodeLines,
  plural,
  rowDetail,
  scrollToLine,
  sourceLines,
  tokenStyle,
} from '../library'

/** One registered workflow, as `GET /api/workflows` sends it. */
function workflow(name: string, nodes: string[]): WorkflowOut {
  return {
    name,
    start: nodes[0] ?? '',
    capacity: 1,
    in_flight: 0,
    nodes: Object.fromEntries(
      nodes.map((node) => [
        node,
        { edges: [], generation: 0, label: node, join: false },
      ]),
    ),
    plugin: { panels: [], actions: [] },
    pool: 'default',
  }
}

/** One run of `wf`, as the run list holds it. */
function run(id: string, wf: string): RunSummary {
  return {
    id,
    workflow: wf,
    title: id,
    status: 'completed',
    position: 1,
    created: '2026-09-08T08:00:00Z',
    updated: '2026-09-08T08:01:00Z',
  }
}

const WORKFLOWS = [
  workflow('feature_build', ['prompt', 'review']),
  workflow('gamedev', ['design']),
]

const RUNS = [
  run('r1', 'feature_build'),
  run('r2', 'gamedev'),
  run('r3', 'feature_build'),
]

const SOURCE: SourceOut = {
  file: '/srv/workflows/feature_build.py',
  source: 'import athanore\n\n@wf.node\ndef prompt(ctx):\n    pass\n',
  nodes: { prompt: { line: 3 } },
}

describe('libraryRows', () => {
  it('is the mock’s row: the name, its nodes, its runs and its file', () => {
    const rows = libraryRows(
      WORKFLOWS,
      RUNS,
      new Map([['feature_build', '/srv/workflows/feature_build.py']]),
    )

    expect(rows).toEqual([
      {
        name: 'feature_build',
        nodes: 2,
        runs: 2,
        file: '/srv/workflows/feature_build.py',
      },
      { name: 'gamedev', nodes: 1, runs: 1, file: undefined },
    ])
  })

  it('keeps the order the server sent, which is by name', () => {
    const rows = libraryRows([...WORKFLOWS].reverse(), RUNS, new Map())

    expect(rows.map((row) => row.name)).toEqual(['gamedev', 'feature_build'])
  })

  it('counts no runs for a workflow nobody has run', () => {
    const rows = libraryRows([workflow('msgtest', ['send'])], RUNS, new Map())

    expect(rows[0]?.runs).toBe(0)
  })

  it('leaves the count unknown when the run list could not be read', () => {
    // 01 §Real data only: a list nobody answered is not a server with no
    // runs, and `0 runs` would say it was.
    const rows = libraryRows(WORKFLOWS, undefined, new Map())

    expect(rows.map((row) => row.runs)).toEqual([undefined, undefined])
  })
})

describe('rowDetail', () => {
  it('is `k runs · file`', () => {
    expect(rowDetail({ name: 'a', nodes: 2, runs: 12, file: 'a.py' })).toBe(
      '12 runs · a.py',
    )
  })

  it('drops the half it does not know', () => {
    expect(rowDetail({ name: 'a', nodes: 2, runs: 12, file: undefined })).toBe(
      '12 runs',
    )
    expect(rowDetail({ name: 'a', nodes: 2, runs: undefined, file: 'a.py' })).toBe(
      'a.py',
    )
  })

  it('is nothing at all when it knows neither', () => {
    expect(
      rowDetail({ name: 'a', nodes: 2, runs: undefined, file: undefined }),
    ).toBeUndefined()
  })
})

describe('plural', () => {
  it('earns the s', () => {
    expect(plural(1, 'node')).toBe('1 node')
    expect(plural(0, 'run')).toBe('0 runs')
    expect(plural(8, 'node')).toBe('8 nodes')
  })
})

describe('initialSelection', () => {
  it('opens on the selected run’s workflow, at the node in focus', () => {
    expect(initialSelection(WORKFLOWS, 'gamedev', 'design')).toEqual({
      workflow: 'gamedev',
      anchor: 'design',
    })
  })

  it('opens on the first workflow when no run is selected', () => {
    expect(initialSelection(WORKFLOWS, undefined, 'design')).toEqual({
      workflow: 'feature_build',
      anchor: undefined,
    })
  })

  it('drops the anchor with the workflow it was about', () => {
    // A run of a workflow this process no longer runs (08 §Runs): the
    // list falls back, and `?node=` named a node of the graph that is
    // not on screen.
    expect(initialSelection(WORKFLOWS, 'deleted_wf', 'engineering')).toEqual({
      workflow: 'feature_build',
      anchor: undefined,
    })
  })

  it('selects nothing when nothing is registered', () => {
    expect(initialSelection([], 'gamedev', 'design')).toEqual({
      workflow: undefined,
      anchor: undefined,
    })
  })
})

describe('sourceLines', () => {
  it('numbers from one and hangs the node on its own line', () => {
    const lines = sourceLines(SOURCE.source, SOURCE.nodes)

    expect(lines.map((line) => line.line)).toEqual([1, 2, 3, 4, 5])
    expect(lines[2]).toEqual({ line: 3, text: '@wf.node', node: 'prompt' })
    expect(lines[3]?.node).toBeUndefined()
  })

  it('does not draw the trailing newline as a sixth line', () => {
    expect(sourceLines('a\nb\n', {})).toHaveLength(2)
    expect(sourceLines('a\nb', {})).toHaveLength(2)
  })

  it('keeps a blank line, because the file has one', () => {
    expect(sourceLines('a\n\nb\n', {})[1]).toEqual({
      line: 2,
      text: '',
      node: undefined,
    })
  })
})

describe('nodeLines', () => {
  it('is the line each node starts on', () => {
    expect(nodeLines({ prompt: { line: 3 }, review: { line: 9 } })).toEqual(
      new Map([
        [3, 'prompt'],
        [9, 'review'],
      ]),
    )
  })

  it('breaks a tie by name, so the same response draws the same anchors', () => {
    expect(nodeLines({ zeta: { line: 4 }, alpha: { line: 4 } })).toEqual(
      new Map([[4, 'alpha']]),
    )
  })
})

describe('anchorLine', () => {
  it('is the node’s line in this file', () => {
    expect(anchorLine(SOURCE, 'prompt')).toBe(3)
  })

  it('is nothing for a node this file does not define', () => {
    // A body imported from another module is left out of `nodes` rather
    // than given a line into text that does not contain it (08).
    expect(anchorLine(SOURCE, 'imported')).toBeUndefined()
    expect(anchorLine(SOURCE, undefined)).toBeUndefined()
    expect(anchorLine(undefined, 'prompt')).toBeUndefined()
  })
})

describe('scrollToLine', () => {
  /** A viewport holding three anchored lines. */
  function viewport(): HTMLElement {
    const element = document.createElement('div')
    element.innerHTML = [1, 2, 3]
      .map((line) => `<span data-line="${String(line)}">line ${String(line)}</span>`)
      .join('')
    return element
  }

  it('scrolls the line into the middle, and says which element it was', () => {
    const scrolled = vi.spyOn(Element.prototype, 'scrollIntoView')
    const container = viewport()

    const target = scrollToLine(container, 2)

    expect(target).toHaveAttribute('data-line', '2')
    expect(scrolled).toHaveBeenCalledWith({ block: 'center' })
    scrolled.mockRestore()
  })

  it('scrolls nothing when there is no line to land on', () => {
    const scrolled = vi.spyOn(Element.prototype, 'scrollIntoView')

    expect(scrollToLine(viewport(), undefined)).toBeNull()
    expect(scrollToLine(viewport(), 99)).toBeNull()
    expect(scrollToLine(null, 2)).toBeNull()
    expect(scrolled).not.toHaveBeenCalled()
    scrolled.mockRestore()
  })
})

describe('tokenStyle', () => {
  /**
   * One themed token. `fontStyle` is a bitfield and shiki types it as an
   * enum whose combinations it does not enumerate, so the combined
   * values a theme really produces are written as the numbers they are.
   */
  function token(over: { color?: string; fontStyle?: number }): ThemedToken {
    return { content: 'x', offset: 0, ...over } as ThemedToken
  }

  it('is the token’s colour', () => {
    expect(tokenStyle(token({ color: '#ff7b72' }))).toEqual({ color: '#ff7b72' })
  })

  it('reads the font bits the theme set', () => {
    expect(tokenStyle(token({ fontStyle: 1 }))).toEqual({ fontStyle: 'italic' })
    expect(tokenStyle(token({ fontStyle: 2 }))).toEqual({ fontWeight: 'bold' })
    expect(tokenStyle(token({ fontStyle: 3 }))).toEqual({
      fontStyle: 'italic',
      fontWeight: 'bold',
    })
    expect(tokenStyle(token({ fontStyle: 12 }))).toEqual({
      textDecoration: 'underline line-through',
    })
  })

  it('sets nothing for a token the theme left alone', () => {
    expect(tokenStyle(token({}))).toEqual({})
  })
})
