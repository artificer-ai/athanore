/**
 * Syntax highlighting, for the two places the app shows code: a markdown
 * panel's fenced blocks (`panes/kinds/MarkdownPane.tsx`) and the
 * workflow library's source viewer (`overlays/Library.tsx`).
 *
 * Its own module, and in `lib/` rather than beside either of them, for
 * three reasons: a component file that exports a function is one React
 * Fast Refresh cannot update in place (`.oxlintrc.json`,
 * `react/only-export-components`); the whole of the shiki decision reads
 * better in one place than spread across two feature folders; and there
 * is **one highlighter for the tab**, so a Python fence in a plugin's
 * markdown and a workflow's module share the grammar they both load.
 *
 * Two shapes come out of it, because the two callers need different
 * things from the same tokens:
 *
 * - {@link highlight} answers shiki's own HTML, which the markdown block
 *   inserts whole. A fenced block is a rectangle of text and nothing in
 *   the app addresses a line of it.
 * - {@link tokenize} answers the tokens, line by line, and the library
 *   draws them itself. That viewer hangs an anchor off every line — a
 *   node's definition is a line number the API sends (08 §Workflows) —
 *   so its lines have to be elements the viewer made, with its own
 *   attributes on them, rather than markup it received as a string.
 */
import type { ShikiTransformer, ThemedToken } from 'shiki'
import type { BundledLanguage, Highlighter } from 'shiki/bundle/web'

/**
 * The highlight theme.
 *
 * Nocturne has no code-token palette of its own (10 §Design system
 * stops at the app's chrome), so this is one of shiki's bundled dark
 * themes with its background dropped: the block sits on the pane's own
 * surface, and only the tokens are the theme's (D160).
 */
export const SHIKI_THEME = 'github-dark-default'

/** Drop shiki's page background; the pane's surface is underneath. */
const TRANSPARENT: ShikiTransformer = {
  name: 'athanore:transparent',
  pre(node) {
    node.properties['style'] = 'background-color:transparent'
  },
}

/** The tab's highlighter, built on the first fenced block and reused. */
let highlighter: Promise<Highlighter> | null = null

async function build(): Promise<Highlighter> {
  const [{ createHighlighter }, { createJavaScriptRegexEngine }] = await Promise.all([
    import('shiki/bundle/web'),
    import('shiki/engine/javascript'),
  ])
  return createHighlighter({
    themes: [SHIKI_THEME],
    langs: [],
    // `forgiving`: a grammar pattern the JavaScript engine cannot
    // express is skipped rather than thrown, so one exotic rule costs
    // its own tokens' colour and not the whole block's.
    engine: createJavaScriptRegexEngine({ forgiving: true }),
  })
}

function shiki(): Promise<Highlighter> {
  if (highlighter === null) {
    highlighter = build().catch((error: unknown) => {
      // A chunk that failed to load may load next time; a rejected
      // promise left in the cache would disable highlighting for the
      // whole tab over one dropped request.
      highlighter = null
      throw error
    })
  }
  return highlighter
}

/** The highlighter with `lang`'s grammar loaded into it. */
async function loaded(lang: string): Promise<Highlighter> {
  const engine = await shiki()
  await engine.loadLanguage(lang as BundledLanguage)
  return engine
}

/** Highlight `code`, or answer `null` and leave the plain block alone. */
export async function highlight(code: string, lang: string): Promise<string | null> {
  try {
    const engine = await loaded(lang)
    return engine.codeToHtml(code, {
      lang: lang as BundledLanguage,
      theme: SHIKI_THEME,
      transformers: [TRANSPARENT],
    })
  } catch {
    // shiki is not there, or the fence named a language it does not
    // know. The plain block is already on screen and stays.
    return null
  }
}

/**
 * `code`'s tokens, one array per line, or `null` to leave it plain.
 *
 * The same failures as {@link highlight} answer the same way: the caller
 * is already drawing the text uncoloured and goes on doing so.
 */
export async function tokenize(
  code: string,
  lang: string,
): Promise<ThemedToken[][] | null> {
  try {
    const engine = await loaded(lang)
    const result = engine.codeToTokens(code, {
      lang: lang as BundledLanguage,
      theme: SHIKI_THEME,
    })
    return result.tokens
  } catch {
    return null
  }
}
