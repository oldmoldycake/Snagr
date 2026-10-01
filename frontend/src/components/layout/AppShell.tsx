import { useLayoutEffect, useRef, type ReactNode } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'
import { Masthead } from './Masthead'
import { ActivitySheet } from '@/features/activity/ActivitySheet'

/** Signed-in page chrome: masthead, a scrolling centered content column, and the activity sheet. */
export function AppShell({ children }: { children: ReactNode }) {
  const mainRef = useMainScrollRestoration()
  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <Masthead />
      <main ref={mainRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto w-full max-w-[1040px] px-6 py-8 md:py-10">{children}</div>
      </main>
      <ActivitySheet />
    </div>
  )
}

/**
 * The page scrolls inside <main>, not the document, and <main> outlives every
 * route, so neither the browser nor the router's <ScrollRestoration> (which
 * only knows the window) does this for us. A new page starts at the top, Back
 * and Forward return to where that history entry was left, and a replace
 * (a range picker, a renamed slug) is the same page and stays put.
 *
 * Positions are recorded as the reader scrolls rather than on the way out: by
 * the time a route change commits, <main> already holds the next page, and a
 * shorter page has clamped the old position away.
 */
function useMainScrollRestoration() {
  const mainRef = useRef<HTMLElement>(null)
  const positions = useRef(new Map<string, number>())
  const { key } = useLocation()
  const navigationType = useNavigationType()

  // Layout effect, so the new page never paints at the old page's offset, and
  // so the old entry's listener is gone before the swap's own scroll event
  useLayoutEffect(() => {
    const main = mainRef.current
    if (!main) return
    if (navigationType === 'POP') main.scrollTop = positions.current.get(key) ?? 0
    else if (navigationType === 'PUSH') main.scrollTop = 0
    const record = () => positions.current.set(key, main.scrollTop)
    // A replace keeps the offset under a new key without scrolling
    record()
    main.addEventListener('scroll', record, { passive: true })
    return () => main.removeEventListener('scroll', record)
  }, [key, navigationType])

  return mainRef
}
