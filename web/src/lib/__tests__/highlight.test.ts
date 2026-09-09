/**
 * `lib/highlight.ts`: the tab's one shiki highlighter, and the promise
 * it makes to both of its callers — **never throw**.
 *
 * A markdown panel's fenced block and the library's source viewer are
 * both already on screen, uncoloured, when they ask for tokens: shiki is
 * a lazy chunk, and a fence may name a grammar the web bundle does not
 * carry. Every failure therefore has to come back as `null` and leave
 * the plain text where it is, which is what this suite asserts — and it
 * asserts the other half too, that a chunk which failed once is asked
 * for again rather than disabling highlighting for the whole tab.
 *
 * shiki itself is not loaded: the two dynamic imports are replaced, so
 * what is under test is this module's caching and its failure paths
 * rather than a grammar somebody else maintains.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/** How many times a highlighter was built, over the whole test. */
let built: number
/** What the next `createHighlighter` does. */
let building: () => Promise<unknown>
/** What the built highlighter's `loadLanguage` does. */
let loading: (lang: string) => Promise<void>

const codeToHtml = vi.fn(() => '<pre>coloured</pre>')
const codeToTokens = vi.fn(() => ({
  tokens: [[{ content: 'assert', color: '#ff7b72', offset: 0 }]],
}))

vi.mock('shiki/bundle/web', () => ({
  createHighlighter: () => {
    built += 1
    return building()
  },
}))

vi.mock('shiki/engine/javascript', () => ({
  createJavaScriptRegexEngine: () => ({ name: 'javascript' }),
}))

/** The module, freshly imported so its one-per-tab cache is empty. */
async function fresh() {
  vi.resetModules()
  return import('../highlight')
}

beforeEach(() => {
  built = 0
  loading = () => Promise.resolve()
  building = () =>
    Promise.resolve({
      loadLanguage: (lang: string) => loading(lang),
      codeToHtml,
      codeToTokens,
    })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe('highlight', () => {
  it('answers shiki’s own HTML, which the markdown block inserts whole', async () => {
    const { SHIKI_THEME, highlight } = await fresh()

    expect(await highlight('assert fps > 55', 'python')).toBe('<pre>coloured</pre>')
    expect(codeToHtml).toHaveBeenCalledWith('assert fps > 55', {
      lang: 'python',
      theme: SHIKI_THEME,
      transformers: [expect.objectContaining({ name: 'athanore:transparent' })],
    })
  })

  it('leaves the plain block alone when the fence names an unknown grammar', async () => {
    const { highlight } = await fresh()
    loading = () => Promise.reject(new Error('no such language: brainfuck'))

    expect(await highlight('+[-]', 'brainfuck')).toBeNull()
  })

  it('leaves it alone when the chunk itself did not load', async () => {
    const { highlight } = await fresh()
    building = () => Promise.reject(new Error('chunk load failed'))

    expect(await highlight('assert fps > 55', 'python')).toBeNull()
  })
})

describe('tokenize', () => {
  it('answers the tokens the library draws its own lines from', async () => {
    const { SHIKI_THEME, tokenize } = await fresh()

    expect(await tokenize('assert fps > 55', 'python')).toEqual([
      [{ content: 'assert', color: '#ff7b72', offset: 0 }],
    ])
    expect(codeToTokens).toHaveBeenCalledWith('assert fps > 55', {
      lang: 'python',
      theme: SHIKI_THEME,
    })
  })

  it('answers null on the same failures, so the viewer stays plain', async () => {
    const { tokenize } = await fresh()
    building = () => Promise.reject(new Error('chunk load failed'))

    expect(await tokenize('wf = Workflow("gamedev")', 'python')).toBeNull()
  })
})

describe('the tab’s one highlighter', () => {
  it('is built once and shared by both callers', async () => {
    const { highlight, tokenize } = await fresh()

    await highlight('assert fps > 55', 'python')
    await tokenize('wf = Workflow("gamedev")', 'python')
    await highlight('const x = 1', 'ts')

    // One grammar cache for the tab: a Python fence in a plugin's
    // markdown and a workflow's module share what they both load.
    expect(built).toBe(1)
  })

  it('is asked for again after a chunk that failed to load', async () => {
    const { highlight } = await fresh()
    building = () => Promise.reject(new Error('chunk load failed'))

    expect(await highlight('assert fps > 55', 'python')).toBeNull()

    // A rejected promise left in the cache would disable highlighting
    // for the whole tab over one dropped request.
    building = () =>
      Promise.resolve({ loadLanguage: loading, codeToHtml, codeToTokens })
    expect(await highlight('assert fps > 55', 'python')).toBe('<pre>coloured</pre>')
    expect(built).toBe(2)
  })
})
