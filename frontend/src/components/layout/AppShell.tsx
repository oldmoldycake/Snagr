import { useEffect, useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react'
import { useLocation, useNavigationType } from 'react-router-dom'
import { Masthead } from './Masthead'
import { ActivitySheet } from '@/features/activity/ActivitySheet'

/** Signed-in page chrome: masthead, a scrolling centered content column, and the activity sheet. */
export function AppShell({ children }: { children: ReactNode }) {
  const mainRef = useMainScrollRestoration()
  useFocusOnNavigation(mainRef)
  // dvh, not vh: only <main> scrolls, so Safari's toolbar never collapses, and
  // a 100vh shell would leave the end of every page behind it
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <Masthead />
      <main ref={mainRef} tabIndex={-1} className="flex-1 overflow-y-auto">
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

/**
 * A route change in a single-page app is silent: nothing tells a screen reader
 * the page changed, and focus stays on the link that was clicked (or falls to
 * the body when that link went with the old page). Moving it to the new page's
 * heading reads the page's name out and starts the next Tab from the top of the
 * page; <main> stands in while the heading is still loading. The first load
 * leaves focus to the browser, and a replace is the same page, so focus stays
 * on the control that changed it. A menu or sheet that navigated leaves focus
 * here as it closes (focusMovedElsewhere) rather than handing it back to its
 * trigger.
 */
function useFocusOnNavigation(mainRef: RefObject<HTMLElement | null>) {
  const { key } = useLocation()
  const navigationType = useNavigationType()
  const shownKey = useRef(key)

  useEffect(() => {
    if (shownKey.current === key) return
    shownKey.current = key
    const main = mainRef.current
    if (!main || navigationType === 'REPLACE') return
    const heading = main.querySelector('h1')
    if (heading) {
      focusHeading(heading)
      return
    }
    main.focus({ preventScroll: true })
    // a page still loading its subject has no heading yet: move on to it when
    // it lands, unless the reader has taken focus somewhere since
    const observer = new MutationObserver(() => {
      const landed = main.querySelector('h1')
      if (!landed) return
      observer.disconnect()
      if (document.activeElement === main) focusHeading(landed)
    })
    observer.observe(main, { childList: true, subtree: true })
    return () => observer.disconnect()
  }, [mainRef, key, navigationType])
}

function focusHeading(heading: HTMLElement) {
  heading.tabIndex = -1
  heading.focus({ preventScroll: true })
}
