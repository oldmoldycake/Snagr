import { useEffect, useLayoutEffect, useRef } from 'react'

/**
 * Seats a tracking marker (the nav's lume bar, a segmented control's plate) on
 * `target` by setting its edges (--l, --r), the target's bottom edge (--t, for
 * the category links, which wrap onto more than one row) and which way it is
 * moving (data-dir). A change of target animates it (`animate`); the first
 * placement and a re-seat after the host changes width (fonts loading, a tab
 * arriving) jump instead.
 */
function seatTrack(host: HTMLElement, marker: HTMLElement, target: HTMLElement | null, animate: boolean) {
  const width = host.clientWidth
  // hidden (the nav below md, a closed collapsible): the resize observer re-seats it when it shows
  if (width === 0) return
  const placed = marker.style.getPropertyValue('--l') !== ''
  const place = (left: number, right: number) => {
    marker.style.setProperty('--l', `${left}px`)
    marker.style.setProperty('--r', `${right}px`)
  }
  const instantly = (move: () => void) => {
    marker.dataset.instant = ''
    move()
    void marker.offsetWidth // commit the jump, so restoring transitions doesn't replay it
    delete marker.dataset.instant
  }

  // nothing to track (a page with no tab, a picker with no value): fold into its own center and fade
  if (!target) {
    if (animate && placed && marker.dataset.state !== 'idle') {
      const center = marker.offsetLeft + marker.offsetWidth / 2
      delete marker.dataset.dir
      place(center, width - center)
    }
    marker.dataset.state = 'idle'
    return
  }

  // offsets, not client rects: a dialog is still scaling in when its picker first seats
  const left = target.offsetLeft
  const right = width - left - target.offsetWidth
  const top = `${target.offsetTop + target.offsetHeight}px`
  const wasIdle = marker.dataset.state === 'idle'
  const sameRow = marker.style.getPropertyValue('--t') === top
  // already there or on its way: the observer's first report lands mid-slide, and a jump would cut it short
  if (
    !wasIdle &&
    sameRow &&
    marker.style.getPropertyValue('--l') === `${left}px` &&
    marker.style.getPropertyValue('--r') === `${right}px`
  ) {
    return
  }
  delete marker.dataset.state
  marker.style.setProperty('--t', top)
  if (!animate) {
    instantly(() => place(left, right))
  } else if (wasIdle || (placed && !sameRow)) {
    // grow out of the new target rather than slide in from wherever the marker
    // was hidden, or slant across from another row
    const center = left + target.offsetWidth / 2
    delete marker.dataset.dir
    instantly(() => place(center, width - center))
    place(left, right)
  } else if (!placed) {
    instantly(() => place(left, right))
  } else {
    // the edge nearest the new target leads and the other catches up
    marker.dataset.dir = left > marker.offsetLeft ? 'right' : 'left'
    place(left, right)
  }
}

/**
 * One marker that tracks the element in the host matching `selector` — the
 * masthead's lume bar, the Segmented plate. It moves whenever `key` changes
 * (read after the new aria-current / aria-checked has committed) and re-seats
 * without animating when the host or its options resize. `from` names where a
 * freshly mounted marker starts, so it slides over from there instead of
 * appearing.
 */
export function useTrack<H extends HTMLElement>(selector: string, key: unknown, from?: string) {
  const hostRef = useRef<H>(null)
  const markerRef = useRef<HTMLSpanElement>(null)
  const fromRef = useRef(from)

  useLayoutEffect(() => {
    const host = hostRef.current
    const marker = markerRef.current
    if (!host || !marker) return
    const start = fromRef.current ? host.querySelector<HTMLElement>(fromRef.current) : null
    fromRef.current = undefined
    if (start) seatTrack(host, marker, start, false)
    seatTrack(host, marker, host.querySelector<HTMLElement>(selector), true)
  }, [selector, key])

  useEffect(() => {
    const host = hostRef.current
    const marker = markerRef.current
    if (!host || !marker) return
    const ro = new ResizeObserver(() => seatTrack(host, marker, host.querySelector<HTMLElement>(selector), false))
    ro.observe(host)
    // the options too: a full-width host keeps its size while fonts load or a label changes
    for (const child of host.children) if (child !== marker) ro.observe(child)
    return () => ro.disconnect()
  }, [selector])

  return { hostRef, markerRef }
}
