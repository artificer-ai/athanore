/**
 * The attention surface outside the app's own window: the tab title, and
 * the desktop notification an operator has opted in to.
 *
 * "The browser tab title prefixes the open-request count; desktop
 * notifications are opt-in." Both are about the same fact and read it
 * from the same place — `GET /api/requests`, the inbox, which is every
 * request still waiting on a person across every run (06 §Surfaces). It
 * is one cache entry, refreshed by `request.*` (10 §Realtime and
 * caching), so the number in the tab and the list in the inbox pane
 * cannot disagree and neither of them polls.
 *
 * **Nothing is notified until something arrives.** The first answer to
 * the inbox is what the operator already has open — a page reloaded on a
 * paused machine holds nine of them — so it seeds the set of requests
 * this tab has seen and raises nothing. After that, a request whose id
 * is new is one that was opened while the operator was looking
 * elsewhere, which is the only thing worth interrupting them for.
 *
 * **Opt-in means the browser's permission and the operator's setting,
 * both.** `usePrefs.notifications` is off by default (T058) and the
 * toggle in the inbox header is what turns it on, asking the browser for
 * permission at the same time — a page that called
 * `Notification.requestPermission()` on load would be one Firefox and
 * Safari ignore, and one nobody asked.
 */
import { useEffect, useRef } from 'react'

import type { RequestView } from '../api/gen/types.gen'
import { usePrefs } from '../store/prefs'
import { useInbox } from './inbox'

/** The tab's title with no requests open; `index.html`'s. */
export const BASE_TITLE = 'Athanore'

/** `(3) Athanore` while three are open, `Athanore` while none are. */
export function titleFor(open: number, base: string = BASE_TITLE): string {
  return open > 0 ? `(${String(open)}) ${base}` : base
}

/** Whether this browser has the Notification API at all. */
export function notificationsAvailable(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window
}

/**
 * Ask the browser for permission, and report whether it was given.
 *
 * Called from the toggle and from nowhere else: a permission prompt is
 * owed to a click (see the module docstring).
 */
export async function requestNotificationPermission(): Promise<boolean> {
  if (!notificationsAvailable()) return false
  if (Notification.permission === 'granted') return true
  if (Notification.permission === 'denied') return false
  try {
    return (await Notification.requestPermission()) === 'granted'
  } catch {
    // Older browsers take a callback instead and reject the promise
    // form. A refusal to be asked is a refusal.
    return false
  }
}

/** The one line a notification carries: which run asked, and what for. */
export function notificationBody(request: RequestView): string {
  return `${request.node} · ${request.prompt}`
}

/**
 * Keep the tab title and the desktop notifications in step with the
 * inbox. Mounted once, by `App`.
 *
 * The title is restored on unmount, which matters to the tests more than
 * to the app: a suite that mounted the shell and moved on would
 * otherwise leave `(2) Athanore` on the document every test after it
 * reads.
 */
export function useAttention(): void {
  const { data } = useInbox()
  const notifications = usePrefs((state) => state.notifications)

  // `null` until the first answer arrives: that is what tells "nothing
  // is open" from "nobody has said yet", and only the second of the two
  // is a reason not to notify.
  const seen = useRef<Set<number> | null>(null)

  // `Array.isArray` and not a null check, for the reason the manifest
  // reads its own answer that way (`panes/manifest.ts`): the tab title
  // is the outermost thing this app writes, and a server that answered
  // with something other than a list must not be able to throw out of an
  // effect the whole shell mounts.
  const inbox = Array.isArray(data) ? data : undefined
  const open = inbox?.length ?? 0

  useEffect(() => {
    document.title = titleFor(open)
    return () => {
      document.title = BASE_TITLE
    }
  }, [open])

  useEffect(() => {
    if (inbox === undefined) return

    const ids = new Set(inbox.map((request) => request.id))
    const first = seen.current === null
    const fresh = first
      ? []
      : inbox.filter((request) => !seen.current?.has(request.id))
    seen.current = ids

    if (first || !notifications) return
    if (!notificationsAvailable() || Notification.permission !== 'granted') return

    for (const request of fresh) {
      new Notification(`Athanore · ${request.kind}`, {
        body: notificationBody(request),
        tag: `athanore-request-${String(request.id)}`,
      })
    }
  }, [inbox, notifications])
}
