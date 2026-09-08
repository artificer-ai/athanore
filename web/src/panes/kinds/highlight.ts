/**
 * Syntax highlighting for a markdown panel's fenced blocks
 * (`./MarkdownPane.tsx`).
 *
 * Its own module for two reasons: a component file that exports a
 * function is one React Fast Refresh cannot update in place
 * (`.oxlintrc.json`, `react/only-export-components`), and the whole of
 * the shiki decision reads better in one place than beside the prose
 * styles.
 */
import type { ShikiTransformer } from 'shiki'
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

/** Highlight `code`, or answer `null` and leave the plain block alone. */
export async function highlight(code: string, lang: string): Promise<string | null> {
  try {
    const engine = await shiki()
    const bundled = lang as BundledLanguage
    await engine.loadLanguage(bundled)
    return engine.codeToHtml(code, {
      lang: bundled,
      theme: SHIKI_THEME,
      transformers: [TRANSPARENT],
    })
  } catch {
    // shiki is not there, or the fence named a language it does not
    // know. The plain block is already on screen and stays.
    return null
  }
}

