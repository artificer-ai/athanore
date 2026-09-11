/**
 * `CustomElementHost`: a plugin's own tag, mounted
 * (`../CustomElementHost.tsx`).
 *
 * Five claims, and every one of them is something an operator would
 * otherwise only find out by opening a plugin's pane and seeing nothing:
 *
 * - the workflow's assets are injected, **once**, as
 *   `<script type="module">`;
 * - the tag renders with `run-id`, `task-id` and `node` on it, and with
 *   nothing else;
 * - `window.athanore` is installed before any of that code could run,
 *   and the element carries its own bridge — on the second mount in a
 *   document as much as on the first, which is the one an already
 *   defined tag makes synchronously;
 * - a workflow that ships nothing draws a card that says so rather than
 *   an empty element.
 *
 * jsdom never executes the injected module — it loads no external
 * resources — so what an element *does* with `window.athanore` is
 * `web/e2e/plugin.spec.ts`'s, in a real browser. What is asserted here
 * is everything the host does before the plugin's first line runs.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'

import { manifestApiPluginsGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import { ASSET_ATTRIBUTE, injectedAssets } from '../../plugins'
import { CustomElementHost } from '../CustomElementHost'
import { GAMEDEV_ENTRY, MANIFEST } from './fixtures'

const RUN = '01JD5XELEMENTHOST0000000'
const OTHER_RUN = '01JD5XELEMENTHOST0000001'

/** An element with the bridge the host put on it (09 §Escape hatch). */
type PluginElement = HTMLElement & {
  athanore?: { fetch: (path: string) => Promise<Response> }
}

/** The one asset `gamedev` ships (`./fixtures.ts`). */
const ASSET = GAMEDEV_ENTRY.assets?.[0] as string

let queryClient: QueryClient

function draw(
  over: Partial<Parameters<typeof CustomElementHost>[0]> = {},
  manifest = MANIFEST,
) {
  queryClient.setQueryData(manifestApiPluginsGetQueryKey(), manifest)
  return render(
    <QueryClientProvider client={queryClient}>
      <CustomElementHost
        tag="gd-playfield"
        workflow="gamedev"
        scope={{ runId: RUN }}
        {...over}
      />
    </QueryClientProvider>,
  )
}

beforeEach(() => {
  queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
})

afterEach(() => {
  for (const script of document.head.querySelectorAll(`script[${ASSET_ATTRIBUTE}]`)) {
    script.remove()
  }
  delete window.athanore
})

describe('the assets', () => {
  it('injects each of the workflow’s assets as a module script', () => {
    draw()

    const script = document.head.querySelector<HTMLScriptElement>(
      `script[${ASSET_ATTRIBUTE}="${ASSET}"]`,
    )
    expect(script).not.toBeNull()
    expect(script?.type).toBe('module')
    expect(script?.getAttribute('src')).toBe(ASSET)
  })

  it('injects them once, however many times the pane is drawn', () => {
    draw().unmount()
    draw().unmount()
    draw()

    // A module cannot be un-executed, so a second `<script>` for one URL
    // would run `customElements.define` twice and throw.
    expect(injectedAssets()).toEqual([ASSET])
  })

  it('injects only the panel’s own workflow’s assets', () => {
    draw({ workflow: 'feature_build', tag: 'fb-diff' })

    expect(injectedAssets()).toEqual([])
  })
})

describe('the element', () => {
  it('renders the tag with the scope on it', () => {
    draw({ scope: { runId: RUN, taskId: 405 }, node: 'qa' })

    const element = screen.getByTestId('plugin-element')
    expect(element.tagName.toLowerCase()).toBe('gd-playfield')
    expect(element).toHaveAttribute('run-id', RUN)
    expect(element).toHaveAttribute('task-id', '405')
    expect(element).toHaveAttribute('node', 'qa')
  })

  it('omits an attribute the scope has no value for', () => {
    draw({ scope: {} })

    const element = screen.getByTestId('plugin-element')
    expect(element).not.toHaveAttribute('run-id')
    expect(element).not.toHaveAttribute('task-id')
    expect(element).not.toHaveAttribute('node')
  })
})

describe('the bridge', () => {
  it('installs window.athanore with the three capabilities and no more', () => {
    draw()

    const athanore = window.athanore
    expect(athanore).toBeDefined()
    expect(Object.keys(athanore ?? {}).sort()).toEqual(['fetch', 'subscribe', 'theme'])
  })

  it('gives the element a bridge bound to its own workflow', async () => {
    draw()

    const element = screen.getByTestId('plugin-element') as HTMLElement & {
      athanore?: { fetch: (path: string) => Promise<Response> }
    }
    expect(element.athanore).toBeDefined()
    // It refuses a path that leaves the workflow's prefix, which is the
    // whole of "bound to /api/plugins/{wf}/" (09 §Escape hatch).
    await expect(element.athanore?.fetch('../../runs')).rejects.toThrow(
      '/api/plugins/gamedev/',
    )
  })

  it('leaves the global installed after the pane goes away', () => {
    draw().unmount()

    // A module that already ran may reach for it at any time; a global
    // that came and went would be a race a plugin author cannot see.
    expect(window.athanore).toBeDefined()
  })
})

describe('an element that is already defined', () => {
  /** What `connectedCallback` could see, one entry per connection. */
  const own: boolean[] = []
  const refusals: Promise<string>[] = []

  class Recorder extends HTMLElement {
    connectedCallback() {
      own.push((this as PluginElement).athanore !== undefined)
      // `window.athanore.fetch` needs a mounted element to know which
      // prefix to resolve against, and `..` leaves whatever prefix it
      // finds: the refusal therefore names the workflow when the global
      // is bound to one, and says there is no element when it is not.
      refusals.push(
        window.athanore?.fetch('..').then(
          () => 'it was not refused',
          (error: unknown) => String(error),
        ) ?? Promise.resolve('there was no global at all'),
      )
    }
  }

  beforeAll(() => customElements.define('gd-recorder', Recorder))
  beforeEach(() => {
    own.length = 0
    refusals.length = 0
  })

  it('sees both bridges every time it is connected, not just the first', async () => {
    // A defined element runs `connectedCallback` synchronously as it is
    // inserted — before a React ref is attached and before any effect —
    // so a host that set the bridges afterwards would work once per
    // document and break on every cycle back to the pane.
    draw({ tag: 'gd-recorder' }).unmount()
    draw({ tag: 'gd-recorder' }).unmount()
    draw({ tag: 'gd-recorder' })

    expect(own).toEqual([true, true, true])
    for (const refusal of await Promise.all(refusals)) {
      expect(refusal).toContain('/api/plugins/gamedev/')
    }
  })

  it('follows the selection by attribute rather than by being rebuilt', () => {
    const drawn = draw({ tag: 'gd-recorder', scope: { runId: RUN } })
    const first = screen.getByTestId('plugin-element')

    drawn.rerender(
      <QueryClientProvider client={queryClient}>
        <CustomElementHost
          tag="gd-recorder"
          workflow="gamedev"
          scope={{ runId: OTHER_RUN, taskId: 405 }}
        />
      </QueryClientProvider>,
    )

    // The same element, with the new scope written onto it: that is what
    // `attributeChangedCallback` is for, and rebuilding would throw away
    // whatever the plugin had drawn.
    expect(screen.getByTestId('plugin-element')).toBe(first)
    expect(first).toHaveAttribute('run-id', OTHER_RUN)
    expect(first).toHaveAttribute('task-id', '405')
    expect(own).toHaveLength(1)
  })
})

describe('a workflow that ships nothing', () => {
  it('draws a card naming the tag rather than an empty element', () => {
    draw({}, [{ ...GAMEDEV_ENTRY, assets: [] }])

    expect(screen.getByTestId('pane-placeholder')).toHaveTextContent('<gd-playfield>')
    expect(screen.queryByTestId('plugin-element')).not.toBeInTheDocument()
    expect(injectedAssets()).toEqual([])
  })

  it('mounts the tag anyway once something else has defined it', () => {
    customElements.define('gd-defined', class extends HTMLElement {})

    draw({ tag: 'gd-defined' }, [{ ...GAMEDEV_ENTRY, assets: [] }])

    expect(screen.getByTestId('plugin-element')).toBeInTheDocument()
  })
})
