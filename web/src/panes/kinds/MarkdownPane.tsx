/**
 * `markdown`: a string of prose (09 §Panel kinds).
 *
 * GitHub-flavoured, because that is the dialect everything else in the
 * app already writes — a work-log deliverable, an agent's report, a
 * plugin's note — so tables, strikethrough and task lists render rather
 * than showing their punctuation.
 *
 * **Shiki is loaded lazily and only where there is code to highlight.**
 * An `import()` inside the code block's effect makes it a chunk the
 * browser fetches the first time a plugin's markdown actually contains a
 * fenced block, and never on a pane that has none. Until it resolves —
 * and for good, if it fails or the fence names a language shiki does not
 * know — the block is the plain `<pre><code>` that is under the
 * highlight anyway, so nothing is hidden waiting for it.
 *
 * Two things about *which* shiki, and both are forced:
 *
 * - the **web** bundle rather than the full one. The full bundle is
 *   every grammar shiki has, which is 300 chunks and 10 MB of wheel for
 *   languages nothing here writes. The web bundle carries the ones this
 *   application's markdown actually contains — Python, shell, JSON,
 *   YAML, SQL, TypeScript, markdown itself — and a fence naming anything
 *   else falls back to the plain block, which is the same degradation an
 *   unknown language already gets;
 * - the **JavaScript RegExp engine** rather than shiki's default
 *   oniguruma one. Oniguruma is WebAssembly, and the policy the SPA is
 *   served under is `script-src 'self'` with no `'wasm-unsafe-eval'` (12
 *   §Plugins, `athanore/api/static.py`): the module loads, the
 *   instantiation is refused, and every block would silently stay plain.
 *   Relaxing the policy for a highlighter is not a trade worth making;
 *   the pure-JS engine renders the same tokens under it (D160).
 *
 * One highlighter for the tab, built on the first block and reused:
 * grammars load into it as fences name them, so a second Python block
 * costs nothing.
 *
 * The markdown is a plugin's, so it is untrusted: `react-markdown`
 * neither renders raw HTML nor runs anything (no `rehype-raw` here), and
 * the only HTML this file inserts as a string is shiki's own output,
 * built from tokens it escaped itself.
 */
import { useEffect, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { highlight } from './highlight'

/** The prose styles, which are the mock's type scale rather than a theme. */
const PROSE = [
  'text-body text-[var(--color-neutral-300)]',
  '[&_h1]:text-kicker [&_h1]:mt-[14px] [&_h1]:mb-[6px] [&_h1]:text-[var(--color-accent-300)]',
  '[&_h2]:text-kicker [&_h2]:mt-[14px] [&_h2]:mb-[6px] [&_h2]:text-[var(--color-accent-300)]',
  '[&_h3]:text-kicker [&_h3]:mt-[12px] [&_h3]:mb-[4px] [&_h3]:text-muted-foreground',
  '[&_p]:my-[6px] [&_p]:max-w-[720px]',
  '[&_ul]:my-[6px] [&_ul]:list-disc [&_ul]:pl-[18px]',
  '[&_ol]:my-[6px] [&_ol]:list-decimal [&_ol]:pl-[18px]',
  '[&_li]:my-[2px]',
  '[&_a]:text-[var(--color-accent-300)] [&_a]:underline',
  '[&_blockquote]:border-l [&_blockquote]:border-[var(--color-neutral-800)] [&_blockquote]:pl-[10px] [&_blockquote]:text-muted-foreground',
  '[&_table]:my-[8px] [&_table]:w-full [&_table]:border-collapse',
  '[&_th]:text-hint [&_th]:border-b [&_th]:border-[var(--color-neutral-900)] [&_th]:px-[8px] [&_th]:py-[4px] [&_th]:text-left [&_th]:tracking-[0.06em] [&_th]:text-muted-foreground',
  '[&_td]:text-row [&_td]:border-b [&_td]:border-[var(--color-neutral-900)] [&_td]:px-[8px] [&_td]:py-[4px]',
  '[&_hr]:my-[10px] [&_hr]:border-[var(--color-neutral-900)]',
  '[&_img]:max-w-full',
].join(' ')

/** The fence's language, from react-markdown's `language-…` class. */
function languageOf(className: string | undefined): string | undefined {
  const match = /(?:^|\s)language-([\w+#-]+)/.exec(className ?? '')
  return match?.[1]
}

function CodeBlock({ code, lang }: { code: string; lang: string | undefined }) {
  const [html, setHtml] = useState<string | null>(null)

  useEffect(() => {
    let live = true
    void highlight(code, lang ?? 'text').then((html) => {
      if (live && html !== null) setHtml(html)
    })
    return () => {
      live = false
    }
  }, [code, lang])

  const frame =
    'bg-zebra my-[8px] overflow-x-auto rounded-lg border border-[var(--color-neutral-900)] p-[10px] [&_pre]:m-0 [&_pre]:whitespace-pre'

  if (html !== null) {
    return (
      <div
        data-testid="code-block"
        data-highlighted="true"
        className={`text-row ${frame}`}
        // shiki's own markup, from tokens it escaped: see the module note.
        dangerouslySetInnerHTML={{ __html: html }}
      />
    )
  }

  return (
    <div data-testid="code-block" data-highlighted="false" className={frame}>
      <pre className="text-row">
        <code>{code}</code>
      </pre>
    </div>
  )
}

export function MarkdownPane({ text }: { text: string }) {
  return (
    <div data-testid="pane-markdown" className={PROSE}>
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children }) {
            const lang = languageOf(className)
            if (lang === undefined && !String(children).includes('\n')) {
              return (
                <code className="bg-zebra rounded-lg px-[4px] py-px text-[var(--color-accent-2-400)]">
                  {children}
                </code>
              )
            }
            return <CodeBlock code={String(children).replace(/\n$/, '')} lang={lang} />
          },
          // The fence's own `<pre>` would wrap the block above in a
          // second one; the block draws its own frame.
          pre({ children }) {
            return <>{children}</>
          },
        }}
      >
        {text}
      </Markdown>
    </div>
  )
}
