/**
 * The strip under the header that says a plugin's JavaScript has changed
 * under this page, and that only a reload can follow it (22 §SPA).
 *
 * The dashboard follows a registration, a reload and a removal without
 * a page reload — the invalidation table refetches the library, the
 * chips, the palette rows and the pane cycle on `workflow.*`
 * (`realtime/invalidate.ts`). The one thing a document cannot follow is
 * a module it has already run: a workflow reloaded with different
 * JavaScript lists its asset at a new `?v=`, and injecting it would run
 * the plugin's `customElements.define` a second time and throw inside
 * its module, so the pane would draw nothing (D225). The honest thing is
 * to keep drawing the element the page has and say so — which is this.
 *
 * It is a strip beside `ServerDownBanner` rather than a toast, because a
 * toast goes away and the fact does not: the store's `staleAssets` is
 * never cleared, so the strip stays up until the operator reloads, and
 * the reload is what makes a document with nothing stale in it. The
 * `reload` prop exists for the unit test — jsdom's `location` cannot be
 * spied on — and defaults to the real thing.
 */
import { useUi } from '../store/ui'

/** The notice's sentence, exactly as 22 §SPA writes it. */
export const STALE_ASSETS_NOTICE = 'plugin code changed — reload the page'

/** What the reload control does when nobody says otherwise. */
function reloadPage(): void {
  window.location.reload()
}

export function PluginAssetsBanner({ reload = reloadPage }: { reload?: () => void }) {
  const staleAssets = useUi((state) => state.staleAssets)
  const workflows = Object.keys(staleAssets).sort((a, b) => a.localeCompare(b))

  if (workflows.length === 0) return null

  return (
    <div
      role="status"
      data-testid="plugin-assets-banner"
      className="text-meta flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[4px] border-b border-border bg-chrome px-[14px] py-[6px] text-muted-foreground"
    >
      <span className="text-status-gate font-medium tracking-[0.12em] uppercase">
        <span aria-hidden>▲ </span>plugin code changed
      </span>
      <span>
        {STALE_ASSETS_NOTICE} — this tab keeps drawing the element it loaded for{' '}
        {workflows.map((workflow, index) => (
          <span key={workflow}>
            {index > 0 ? ', ' : ''}
            <Code>{workflow}</Code>
          </span>
        ))}
        .
      </span>
      <button
        type="button"
        onClick={reload}
        className="rounded-lg border border-border px-[8px] py-px text-[var(--color-accent-200)] hover:border-[var(--color-accent-600)] hover:bg-[var(--color-accent-900)]"
      >
        reload
      </button>
    </div>
  )
}

function Code({ children }: { children: string }) {
  return (
    <code
      data-testid="plugin-assets-workflow"
      className="rounded-sm bg-[var(--color-neutral-900)] px-[4px] py-px text-[var(--color-accent-200)]"
    >
      {children}
    </code>
  )
}
