/**
 * `TokenScreen`: what a network bind asks the operator for, and the one
 * place the answer is kept.
 *
 * On the default loopback deployment this is never drawn: `/api/me`
 * reports `auth: "off"`, nothing is asked, and 12's "a machine that
 * never binds a network never sees a login" holds. `AppGate` decides;
 * this is the screen it shows when the server wants a token and this
 * browser has not got a good one — because `/api/me` said so, or
 * because some request came back `401` (`src/api/client.ts`).
 *
 * What it does with what it is given is three things and no more:
 *
 * - **stores it in `usePrefs`**, which persists to `localStorage` (10
 *   §Auth in the browser, T058). From there the API client sends it as
 *   a bearer header and the event feed appends it to the stream's URL as
 *   `access_token` — the one sanctioned query parameter, because
 *   `EventSource` cannot set a header (08 §Auth, `src/realtime/sse.ts`).
 *   The feed watches the stored token and reconnects the moment it
 *   changes, so a stream that a refusal closed comes back with the new
 *   credential rather than after a 30 s backoff.
 * - **drops everything this tab fetched without it.** A cache filled
 *   before the operator proved who they were was filled as somebody
 *   else — or as nobody — so it is marked stale rather than shown to
 *   the operator who has just arrived. `refetchType: 'none'` because the
 *   shell is unmounted behind this screen: the queries refetch as they
 *   mount, and `/api/me` is asked for here, once, by name.
 * - **asks `/api/me` again**, which is the only question that can end
 *   this screen: it is unauthenticated by design and answers on a server
 *   that would refuse everything else (08 §System), and its
 *   `authenticated` describes the request that asked it — the one this
 *   screen has just given a credential to.
 *
 * The token is never put in application state beyond that, never logged,
 * and never rendered back: the field is a password field, and `forget
 * it` is how a token this browser should stop sending goes away.
 */
import { useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'

import { useMe } from '../api/client'
import { usePrefs } from '../store/prefs'
import { useUi } from '../store/ui'
import { Curtain, CurtainButton, CurtainCode, CurtainPanel } from './Curtain'

/** The panel's kicker, and so the dialog's accessible name. */
export const TOKEN_SCREEN_TITLE = 'token required'

export function TokenScreen() {
  const me = useMe()
  const queryClient = useQueryClient()
  const stored = usePrefs((state) => state.token)
  const setToken = usePrefs((state) => state.setToken)
  const setNeedsToken = useUi((state) => state.setNeedsToken)

  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)

  // A token this browser holds while this screen is up is a token the
  // server has refused: it is sent on every request, `/api/me` included
  // (D154), so `authenticated: false` and a `401` say the same thing
  // about it. Not while a submission is in flight — that one has not
  // been answered yet.
  const refused = stored !== null && !busy

  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const token = value.trim()
    if (token === '' || busy) return

    setBusy(true)
    setToken(token)
    // The refusal that raised this screen was about the old credential.
    // Clearing it here means `/api/me`'s answer decides what is next,
    // and a fresh `401` can raise it again.
    setNeedsToken(false)
    void queryClient.invalidateQueries({ refetchType: 'none' })
    try {
      await me.refetch()
    } finally {
      // The field is cleared whichever way it went: on success this
      // screen is unmounted, and on a refusal a token that has just
      // been refused is not a draft worth keeping.
      setValue('')
      setBusy(false)
    }
  }

  /**
   * Stop sending the token this browser holds.
   *
   * `AppGate` shows this screen for a `token` server that has no token
   * to send, so forgetting one is the whole of it — no request is
   * needed, and the app cannot be left showing data fetched under a
   * credential it no longer has.
   */
  const forget = () => {
    setToken(null)
    setNeedsToken(false)
    void queryClient.invalidateQueries({ refetchType: 'none' })
    setValue('')
  }

  return (
    <Curtain>
      <CurtainPanel kicker={TOKEN_SCREEN_TITLE}>
        <p className="text-body text-[var(--color-neutral-300)]">
          {refused
            ? 'This server refused the token this browser holds.'
            : 'This server answers operator requests only to a token this browser has not got.'}
        </p>

        <form onSubmit={save} className="flex flex-col gap-[10px]">
          <input
            type="password"
            name="operator-token"
            value={value}
            autoFocus
            autoComplete="off"
            spellCheck={false}
            onChange={(event) => {
              setValue(event.target.value)
            }}
            aria-label="operator token"
            placeholder="operator token"
            className="text-meta w-full rounded-lg border border-border bg-card px-[8px] py-[5px] text-foreground outline-none placeholder:text-[var(--color-neutral-600)] focus:border-[var(--color-accent-600)]"
          />

          <div className="flex items-center gap-[8px]">
            <CurtainButton type="submit" disabled={busy || value.trim() === ''}>
              {busy ? 'checking…' : 'save token'}
            </CurtainButton>
            {stored !== null && (
              <CurtainButton onClick={forget} disabled={busy}>
                forget it
              </CurtainButton>
            )}
          </div>
        </form>

        <p className="text-meta text-muted-foreground">
          <CurtainCode>athanore token show</CurtainCode> prints it, on the machine
          serving this page.
        </p>
      </CurtainPanel>
    </Curtain>
  )
}
