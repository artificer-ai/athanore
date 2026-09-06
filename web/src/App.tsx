/**
 * The placeholder shell: the brand mark on the Nocturne background, and
 * nothing else. The header, run list, panes and overlays of
 * docs/v1/10-frontend.md arrive from T057 onward.
 */
export default function App() {
  return (
    <main className="flex h-dvh items-center justify-center bg-background text-foreground">
      <h1 className="text-body font-bold tracking-[0.12em] text-[var(--color-accent-300)]">
        ▚ ATHANORE
      </h1>
    </main>
  )
}
