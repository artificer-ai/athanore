/**
 * The measured content width of one element, for the layouts that a
 * media query cannot decide.
 *
 * `useIsNarrow` asks the *viewport* which of the app's two layouts is
 * being drawn, and that is the right question for the shell. It is the
 * wrong question for a pane: a pane's width is the viewport minus the
 * run list, minus the splitter's position, divided by the pane cycle —
 * so a 900 px window can hand a pane 460 px, and a 768 px window with
 * the run list hidden can hand it 740 px. A component that must choose
 * between two column layouts has to measure the box it is actually in.
 *
 * `null` means "not measured yet", and a caller is expected to have an
 * answer for that — the first paint happens before the observer's first
 * callback, and a hidden subtree (`display: none`) never reports a width
 * at all. Zero is never reported as a width for the same reason: a box
 * that is not being laid out has no width to speak of, and treating its
 * zero as a measurement would flip the layout every time the pane were
 * hidden.
 */
import { useEffect, useState } from 'react'

export function useElementWidth(): [(node: Element | null) => void, number | null] {
  // The node is state and not a ref, because the element this measures
  // mounts later than the component does — the graph pane draws a
  // placeholder until its query answers — and a ref's identity never
  // changes, so an effect keyed on one would observe nothing.
  const [node, setNode] = useState<Element | null>(null)
  const [width, setWidth] = useState<number | null>(null)

  useEffect(() => {
    if (node === null) return
    const observer = new ResizeObserver((entries) => {
      const measured = entries.at(-1)?.contentRect.width
      if (measured !== undefined && measured > 0) setWidth(measured)
    })
    observer.observe(node)
    return () => {
      observer.disconnect()
    }
  }, [node])

  return [setNode, width]
}
