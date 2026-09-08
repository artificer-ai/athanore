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
 * Three things send it to the token screen, and they are one thing seen
 * from three sides (10 §Auth in the browser):
 *
 * - a `401` from anywhere, which the API client's interceptor records as
 *   `needsToken`: the token this browser holds is missing or no longer
 *   good, whichever endpoint found out;
 * - `/api/me` reporting `auth: "token"` and `authenticated: false`,
 *   which is the same fact without a refusal to prove it — the request
 *   that asked carried whatever token this browser holds (D154);
 * - a stored token that has gone away while the app was up. `/api/me`
 *   said `authenticated` about a request that carried it, so a browser
 *   that no longer holds it can no longer authenticate, and waiting for
 *   the next refusal to say so would leave the operator looking at data
 *   they can no longer refresh.
 */
import type { ReactNode } from 'react'

import { useMe } from '../api/client'
import { Curtain, CurtainButton, CurtainCode, CurtainPanel } from '../components/Curtain'
import { TokenScreen } from '../components/TokenScreen'
import { usePrefs } from '../store/prefs'
import { useUi } from '../store/ui'

export function AppGate({ children }: { children: ReactNode }) {
  const me = useMe()
  const token = usePrefs((s) => s.token)
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
        <CurtainPanel kicker="no server">
          <p className="text-body text-[var(--color-neutral-300)]">
            Nothing answered <CurtainCode>GET /api/me</CurtainCode> at this
            address.
          </p>
          <p className="text-meta text-muted-foreground">
            Start it with <CurtainCode>athanore serve</CurtainCode>, then try
            again.
          </p>
          <CurtainButton onClick={retry}>try again</CurtainButton>
        </CurtainPanel>
      </Curtain>
    )
  }

  const wantsToken = me.data.auth === 'token'
  if (needsToken || (wantsToken && (!me.data.authenticated || token === null))) {
    return <TokenScreen />
  }

  return <>{children}</>
}
