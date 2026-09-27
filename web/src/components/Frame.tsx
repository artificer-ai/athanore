/**
 * The Terminal mock's section frame: `┤ STATS ├` (D277).
 *
 * The box-drawing is chrome, not the title, so both halves are
 * `aria-hidden`: a screen reader hears "STATS", and a heading's
 * accessible name is the word the section is about.
 */
import type { ReactNode } from 'react'

export function Frame({ children }: { children: ReactNode }) {
  return (
    <>
      <span aria-hidden>┤ </span>
      {children}
      <span aria-hidden> ├</span>
    </>
  )
}
