/**
 * The inbox: every open request across every run, newest first.
 *
 * The `global` twin of the requests pane. Both are the `<ath-requests>`
 * element of `athanore/plugins/builtin/requests.py`, and what tells them
 * apart is the scope they are drawn in: with a run selected the pane is
 * that run's whole human-in-the-loop history, and with none it is this —
 * "an operator who opens the app to a list of runs can still see what is
 * waiting on them".
 *
 * **Newest first, which is the opposite of the run's pane.** A history
 * reads forwards; a queue of things waiting on you reads with the
 * freshest at the top, and 06 §SPA says so outright. `GET /api/requests`
 * answers oldest first and says that is not a presentation
 * (`athanore/store/repos/requests.py`), so the order is made here.
 *
 * **It asks for the pending ones only**, which is the route's own
 * default: a stale request is out of the inbox because an answer to it
 * would reach nobody (06 §Restart durability), and an answered one is
 * history that belongs to its run. The query carries no options at all,
 * so its key is exactly `queryKeys.inbox()` — the entry `request.*`
 * invalidates (10 §Realtime and caching), and the one the panel refetches
 * after it answers.
 */
import { toast } from 'sonner'

import { cn } from '../lib/utils'
import { ErrorCard } from '../panes/kinds/cards'
import { requestsError } from '../panes/kinds/requests'
import { usePrefs } from '../store/prefs'
import { PENDING_GLYPH, RequestCard } from './RequestCard'
import { notificationsAvailable, requestNotificationPermission } from './attention'
import { newestFirst, useInbox } from './inbox'

/** The mock's header separator: a neutral-800 pipe between the parts. */
function Bar() {
  return <span className="text-[var(--color-neutral-800)]">│</span>
}

/**
 * The opt-in of 10 §Attention, where the requests are.
 *
 * Desktop notifications need two yeses: the operator's, which is
 * `usePrefs.notifications` and off by default (T058), and the browser's,
 * which may only be asked for from a gesture. This toggle is that
 * gesture, and it is here because the inbox is the surface a notified
 * operator comes back to.
 *
 * A browser with no Notification API draws no toggle: there is nothing
 * to opt in to. One that has already refused says so and leaves the
 * setting off, because turning it on would promise a notification the
 * browser will not deliver.
 */
function NotifyToggle() {
  const on = usePrefs((state) => state.notifications)
  const setNotifications = usePrefs((state) => state.setNotifications)

  if (!notificationsAvailable()) return null

  return (
    <button
      type="button"
      data-testid="inbox-notify"
      aria-pressed={on}
      title="desktop notifications for new requests"
      onClick={() => {
        if (on) {
          setNotifications(false)
          return
        }
        void requestNotificationPermission().then((granted) => {
          if (granted) setNotifications(true)
          else toast('this browser will not show notifications for Athanore')
        })
      }}
      className={cn(
        'text-hint cursor-pointer rounded-lg border px-[7px] py-[1px] tracking-[0.1em]',
        on
          ? 'border-[var(--color-accent-700)] text-[var(--color-accent-200)]'
          : 'border-border text-muted-foreground hover:text-[var(--color-neutral-300)]',
      )}
    >
      {on ? '● notify' : '○ notify'}
    </button>
  )
}

/** A status line: what the inbox is waiting for, or has nothing of. */
function Status({ children }: { children: string }) {
  return (
    <p className="text-row p-[12px_14px] text-muted-foreground" role="status">
      {children}
    </p>
  )
}

export function Inbox() {
  const { data, isError, error } = useInbox()
  const requests = data ?? []

  return (
    <div data-testid="pane-inbox" className="flex min-h-0 flex-1 flex-col">
      <div className="text-hint flex flex-none flex-wrap items-center gap-x-[10px] gap-y-[6px] border-b border-[var(--color-neutral-900)] px-[14px] py-[6px] tracking-[0.1em] text-muted-foreground">
        <span>INBOX</span>
        <Bar />
        <span>every run</span>
        <div className="flex-1" />
        <NotifyToggle />
        {data !== undefined && (
          <span
            data-testid="inbox-count"
            className={cn(
              'whitespace-nowrap',
              requests.length > 0
                ? 'text-status-gate'
                : 'text-[var(--color-neutral-500)]',
            )}
          >
            {requests.length > 0
              ? `${PENDING_GLYPH} ${String(requests.length)} open`
              : '○ none open'}
          </span>
        )}
      </div>

      {isError ? (
        // The inbox makes its own request, so a refusal is named here
        // rather than left to look like a machine with nothing waiting.
        <div className="p-[12px_14px]">
          <ErrorCard {...requestsError(error)} source="/api/requests" />
        </div>
      ) : data === undefined ? (
        <Status>loading the inbox…</Status>
      ) : requests.length === 0 ? (
        <Status>nothing is waiting on you</Status>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col gap-[8px] overflow-x-hidden overflow-y-auto px-[14px] pt-[12px] pb-[24px]">
          {newestFirst(requests).map((request) => (
            <RequestCard key={request.id} request={request} showRun />
          ))}
        </div>
      )}
    </div>
  )
}
