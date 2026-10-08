import { useEffect } from 'react'

/** The tab title for a page: its own name first, so a row of tabs stays tellable apart once truncated. */
export function pageTitle(title?: string): string {
  return title ? `${title} · Snagr` : 'Snagr'
}

/**
 * Names the browser tab after the page showing in it. Pass undefined while the
 * page's subject is still loading; the tab reads plain "Snagr" until it lands.
 */
export function usePageTitle(title?: string) {
  useEffect(() => {
    document.title = pageTitle(title)
  }, [title])
}
