/**
 * `window.athanore`: the three capabilities, and the boundary around
 * each (`../bridge.ts`).
 *
 * The boundary is the subject. A plugin's JavaScript runs in the
 * operator's browser with the operator's token (12 §Plugins) — that is
 * one trust decision, made at install time — and what this file asserts
 * is that the *host* still says where a request may go, which
 * credential it carries, and what a refusal does. `fetch` bound to a
 * prefix and refusing to leave it is the whole of "bound to
 * /api/plugins/{wf}/".
 */
import { QueryClient } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { createAppQueryClient } from '../../api/client'
import { meApiMeGetQueryKey } from '../../api/gen/@tanstack/react-query.gen'
import type { AthanoreEvent } from '../../realtime/invalidate'
import { createAppEventFeed, type EventSourceLike } from '../../realtime/sse'
import { usePrefs } from '../../store/prefs'
import { useUi } from '../../store/ui'
import { THEME_TOKENS } from '../../styles/tokens.gen'
import { bindPluginBridge, pluginBridge, pluginUrl, themeTokens } from '../bridge'

const TOKEN = 'operator-token'

let queryClient: QueryClient

/** Answer every request, recording the URL and the headers it carried. */
function stubFetch(status = 200) {
  const calls: { url: string; authorization: string | null }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({
        url,
        authorization: new Headers(init?.headers).get('Authorization'),
      })
      return new Response('{}', { status })
    }),
  )
  return calls
}

beforeEach(() => {
  queryClient = createAppQueryClient()
  usePrefs.setState({ token: null })
  useUi.setState({ needsToken: false })
})

afterEach(() => {
  vi.unstubAllGlobals()
  queryClient.clear()
})

describe('pluginUrl', () => {
  it.each([
    ['/words', '/api/plugins/gamedev/words'],
    ['words', '/api/plugins/gamedev/words'],
    ['./words', '/api/plugins/gamedev/words'],
    ['/words?limit=5', '/api/plugins/gamedev/words?limit=5'],
    ['/a/b', '/api/plugins/gamedev/a/b'],
  ])('resolves %s under the workflow’s prefix', (path, expected) => {
    expect(pluginUrl('gamedev', path)).toBe(expected)
  })

  it.each([
    '../words',
    '/../../runs',
    '../../../api/runs',
    // Percent-encoded dot segments are dot segments to the URL parser,
    // so this leaves the prefix too rather than naming a route in it.
    '/%2e%2e/runs',
    'https://evil.example/x',
    'http://evil.example/x',
    // Protocol-relative: `//host/x` names another origin, and the
    // leading slashes are *not* stripped off it into a path under the
    // prefix. A backslash is a slash to the URL parser in a special
    // scheme, so `/\\host/x` is the same request wearing a hat.
    '//evil.example/x',
    '///evil.example/x',
    '//',
    '/\\evil.example/x',
  ])('refuses %s, which names no route under the prefix', (path) => {
    expect(() => pluginUrl('gamedev', path)).toThrow(TypeError)
  })
})

describe('fetch', () => {
  it('asks the workflow’s own route', async () => {
    const calls = stubFetch()

    await pluginBridge('gamedev').fetch('/words?limit=5')

    expect(calls.map((call) => call.url)).toEqual([
      '/api/plugins/gamedev/words?limit=5',
    ])
  })

  it('carries the operator credential the typed calls carry', async () => {
    const calls = stubFetch()
    usePrefs.setState({ token: TOKEN })

    await pluginBridge('gamedev').fetch('/words')

    // A plugin route is an operator route (12 §Plugins), so the rule is
    // the one `src/api/client.ts` applies to everything.
    expect(calls[0]?.authorization).toBe(`Bearer ${TOKEN}`)
  })

  it('withholds it from a server that answered auth: off', async () => {
    const calls = stubFetch()
    usePrefs.setState({ token: TOKEN })
    queryClient.setQueryData(meApiMeGetQueryKey(), {
      auth: 'off',
      authenticated: true,
    })

    await pluginBridge('gamedev').fetch('/words')

    expect(calls[0]?.authorization).toBeNull()
  })

  it('asks for the token screen when a plugin route answers 401', async () => {
    stubFetch(401)

    const response = await pluginBridge('gamedev').fetch('/words')

    expect(response.status).toBe(401)
    expect(useUi.getState().needsToken).toBe(true)
  })

  it('refuses to leave the prefix before a request is made', async () => {
    const calls = stubFetch()

    await expect(pluginBridge('gamedev').fetch('../../runs')).rejects.toThrow(TypeError)
    expect(calls).toEqual([])
  })
})

describe('subscribe', () => {
  // First, and deliberately: `createAppEventFeed` sets the tab's feed
  // for the rest of the file, and "no feed at all" is only true before
  // one has ever been made.
  it('says so rather than subscribing to a feed that is not open', () => {
    expect(() => pluginBridge('gamedev').subscribe(['log.appended'], () => {})).toThrow(
      'no event feed open',
    )
  })

  /** A feed a test drives: one `EventSource` this file dispatches into. */
  function openFeed() {
    const listeners = new Map<string, ((event: Event) => void)[]>()
    const source: EventSourceLike = {
      addEventListener: (type, listener) => {
        listeners.set(type, [...(listeners.get(type) ?? []), listener])
      },
      close: () => {},
    }
    const feed = createAppEventFeed(queryClient, {
      open: () => source,
      onState: () => {},
    })
    feed.start()
    const send = (event: AthanoreEvent) => {
      for (const listener of listeners.get(event.name) ?? []) {
        listener(new MessageEvent(event.name, { data: JSON.stringify(event) }))
      }
    }
    return { feed, send }
  }

  /**
   * One frame off the feed.
   *
   * Cast through `unknown`: the generated union is discriminated on
   * `name`, and what is under test is a *filter over names* — including
   * names no build's union carries, since a plugin's own
   * `plugin.<wf>.<name>` events are whatever the plugin publishes.
   */
  function event(name: string): AthanoreEvent {
    return {
      id: 1,
      name,
      created: '2026-09-09T10:00:00Z',
      run_id: null,
      task_id: null,
      node: null,
      data: {},
    } as unknown as AthanoreEvent
  }

  it('delivers the names it was given, and no others', () => {
    const { feed, send } = openFeed()
    const seen: string[] = []

    const stop = pluginBridge('gamedev').subscribe(['log.appended'], (e) => {
      seen.push(e.name)
    })
    send(event('log.appended'))
    send(event('run.completed'))
    stop()
    send(event('log.appended'))
    feed.stop()

    expect(seen).toEqual(['log.appended'])
  })

  it('matches a name as a glob, the way refresh_on does', () => {
    const { feed, send } = openFeed()
    const seen: string[] = []

    pluginBridge('gamedev').subscribe(['task.*'], (e) => seen.push(e.name))
    send(event('task.done'))
    send(event('run.started'))
    feed.stop()

    expect(seen).toEqual(['task.done'])
  })

  it('does not let a subscriber that throws break the feed', () => {
    const { feed, send } = openFeed()
    const seen: string[] = []
    vi.spyOn(console, 'error').mockImplementation(() => {})

    const bridge = pluginBridge('gamedev')
    bridge.subscribe(['log.appended'], () => {
      throw new Error('the plugin is broken')
    })
    bridge.subscribe(['log.appended'], (e) => seen.push(e.name))
    send(event('log.appended'))
    feed.stop()

    // A plugin cannot break the engine (09 §Mounting); this is the same
    // promise in the browser.
    expect(seen).toEqual(['log.appended'])
  })

})

describe('theme', () => {
  it('carries every token of the design system', () => {
    const { tokens } = pluginBridge('gamedev').theme

    expect(Object.keys(tokens)).toEqual(THEME_TOKENS.map((token) => token.name))
    expect(tokens['--color-accent']).toBe('#9184d9')
  })

  it('prefers what the document resolves over the generated value', () => {
    document.documentElement.style.setProperty('--color-accent', 'rebeccapurple')

    expect(themeTokens()['--color-accent']).toBe('rebeccapurple')

    document.documentElement.style.removeProperty('--color-accent')
  })
})

describe('window.athanore', () => {
  /** Mount an element of each workflow; the release undoes all of them. */
  function mount(...workflows: string[]): () => void {
    const released = workflows.map((workflow) => bindPluginBridge(workflow))
    return () => {
      for (const release of released.reverse()) release()
    }
  }

  afterEach(() => {
    delete window.athanore
  })

  it('is not installed until an element is mounted', () => {
    // First in this block, and deliberately: the global is installed for
    // the life of the document once anything has mounted.
    expect(window.athanore).toBeUndefined()
  })

  it('carries the three capabilities and no more', () => {
    const unmount = mount('gamedev')

    expect(Object.keys(window.athanore ?? {}).sort()).toEqual([
      'fetch',
      'subscribe',
      'theme',
    ])

    unmount()
  })

  it('resolves a relative path against the workflow mounted last', async () => {
    const calls = stubFetch()
    const unmountFirst = mount('gamedev')
    const unmountSecond = mount('feature_build')

    await window.athanore?.fetch('/diff')
    unmountSecond()
    await window.athanore?.fetch('/words')
    unmountFirst()

    expect(calls.map((call) => call.url)).toEqual([
      '/api/plugins/feature_build/diff',
      '/api/plugins/gamedev/words',
    ])
  })

  it('refuses a path when no element is mounted at all', async () => {
    mount('gamedev')()

    await expect(window.athanore?.fetch('/words')).rejects.toThrow(
      'no plugin element is mounted',
    )
  })

  it('is put back on a document that lost it', () => {
    const unmount = mount('gamedev')
    const first = window.athanore
    delete window.athanore

    mount('gamedev')()

    expect(window.athanore).toBe(first)
    unmount()
  })
})
