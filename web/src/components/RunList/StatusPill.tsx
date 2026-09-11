/**
 * The status pill: an outlined badge carrying the status word in its
 * status colour.
 *
 * The border is neutral, as it is in the mock's pane bar — the colour is
 * the text's — and the word is always there, because 10 §Accessibility
 * says colour is never the only signal. `running` pulses; every other
 * tone is plain (§Status colours), and `prefers-reduced-motion` stops
 * the pulse in `theme.css`.
 */
import { cn } from '../../lib/utils'
import { toneClass, tonePulses, type StatusTone } from './status'

export function StatusPill({
  status,
  tone,
  className,
}: {
  status: string
  tone: StatusTone
  className?: string
}) {
  return (
    <span
      data-tone={tone}
      className={cn(
        'inline-block max-w-full truncate rounded-lg border border-border px-[7px] py-px text-[calc(10.5rem/12)] tracking-[0.06em]',
        toneClass(tone),
        tonePulses(tone) && 'animate-ath-pulse',
        className,
      )}
    >
      {status}
    </span>
  )
}
