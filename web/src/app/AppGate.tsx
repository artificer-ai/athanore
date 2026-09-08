/**
 * The gate between "this browser may use this server" and the app.
 *
 * `GET /api/me` is the one question worth asking before anything else:
 * it is unauthenticated by design, so it answers on a server that would
 * refuse every other request (08 §System). What it answers decides which
 * of four things is on screen — the app, the token screen, the reason
 * the server could not be reached, or nothing yet.
 *
 * On the default loopback deployment the answer is `auth: "off"` and
 * `authenticated: true`, and the operator is never asked for anything:
 * that is 12 §Operator token's "a machine that never binds a network
 * never sees a login", and it is the case this gate exists to keep
 * invisible.
 *
 * The token screen itself is T065; what stands in its place here is the
 * notice that says why the app is not showing, and the button that asks
 * the server again.
 */
import type { ReactNode } from 'react'

import { useMe } from '../api/client'
import { useUi } from '../store/ui'

export function AppGate({ children }: { children: ReactNode }) {
  const me = useMe()
  const needsToken = useUi((s) => s.needsToken)
  const setNeedsToken = useUi((s) => s.setNeedsToken)

  /** Ask the server again, from a clean slate. */
  const retry = () => {
    setNeedsToken(false)
    void me.refetch()
  }

  if (me.isPending) {
    return (
      <Curtain>
        <p role="status" className="text-meta text-muted-foreground">
          connecting…
        </p>
      </Curtain>
    )
  }

  if (me.isError) {
    return (
      <Curtain>
        <Panel kicker="no server">
          <p className="text-body text-[var(--color-neutral-300)]">
            Nothing answered <Code>GET /api/me</Code> at this address.
          </p>
          <p className="text-meta text-muted-foreground">
            Start it with <Code>athanore serve</Code>, then try again.
          </p>
          <Retry onClick={retry} />
        </Panel>
      </Curtain>
    )
  }

  // A refusal from any endpoint, or `/api/me` itself saying this server
  // wants a token that this caller has not got (10 §Auth in the browser).
  if (needsToken || (me.data.auth === 'token' && !me.data.authenticated)) {
    return (
      <Curtain>
        <Panel kicker="token required">
          <p className="text-body text-[var(--color-neutral-300)]">
            This server answers operator requests only to a token this browser
            has not got.
          </p>
          <p className="text-meta text-muted-foreground">
            <Code>athanore token show</Code> prints it.
          </p>
          <Retry onClick={retry} />
        </Panel>
      </Curtain>
    )
  }

  return <>{children}</>
}

/** A full-screen backdrop with its panel centred (10 §Overlays). */
function Curtain({ children }: { children: ReactNode }) {
  return (
    <div
      data-testid="app-gate-curtain"
      className="flex h-dvh items-center justify-center bg-[rgba(10,11,18,.72)] p-[24px]"
    >
      {children}
    </div>
  )
}

/** The overlay surface of 10 §Overlays: 1 px neutral-800, 8 px, shadow-lg. */
function Panel({ kicker, children }: { kicker: string; children: ReactNode }) {
  return (
    <div
      role="dialog"
      aria-label={kicker}
      className="flex w-full max-w-[460px] flex-col gap-[10px] rounded-lg border border-[var(--color-neutral-800)] bg-[var(--color-surface)] p-[18px] shadow-[var(--shadow-lg)]"
    >
      <h2 className="text-kicker text-[var(--color-accent-300)]">{kicker}</h2>
      {children}
    </div>
  )
}

function Code({ children }: { children: ReactNode }) {
  return (
    <code className="text-meta rounded-sm bg-[var(--color-neutral-900)] px-[4px] py-px text-[var(--color-accent-200)]">
      {children}
    </code>
  )
}

function Retry({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="text-meta mt-[4px] self-start rounded-lg border border-border px-[10px] py-[4px] text-[var(--color-accent-200)] hover:border-[var(--color-accent-600)] hover:bg-[var(--color-accent-900)]"
    >
      try again
    </button>
  )
}
