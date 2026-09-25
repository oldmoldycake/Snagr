import { useEffect } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { useTrack } from '@/lib/useTrack'
import { useInstance, useSession } from '@/features/auth/useSession'

/**
 * The tab the plate sat on while a settings page was showing. Each page mounts
 * its own tabs, so the next one starts its plate there and slides it over.
 */
let lastTab: string | null = null

/**
 * The settings sub-navigation — one route per tab, styled as the Segmented
 * control's routed twin so the page reads as one system. Tabs the viewer can't
 * use drop out (Users is admin-only; MCP & API goes when the operator turned
 * agent access off), the way the vision link drops out of the masthead.
 */
export function SettingsTabs() {
  const { data: user } = useSession()
  const { data: instance } = useInstance()
  const { pathname } = useLocation()
  const { hostRef, markerRef } = useTrack<HTMLElement>(
    'a[aria-current="page"]',
    pathname,
    lastTab ? `a[href="${lastTab}"]` : undefined,
  )
  // cleared on the way out, so arriving from elsewhere in the app places the plate without a slide
  useEffect(() => {
    lastTab = pathname
    return () => {
      lastTab = null
    }
  }, [pathname])

  const tabs: { to: string; label: string; end?: boolean }[] = [
    { to: '/settings', label: 'General', end: true },
  ]
  if (instance?.mcp_enabled) tabs.push({ to: '/settings/api', label: 'MCP & API' })
  if (user?.role === 'admin') tabs.push({ to: '/settings/users', label: 'Users' })

  return (
    <nav
      ref={hostRef}
      aria-label="Settings sections"
      className="relative inline-flex gap-0.5 rounded-sm border border-hairline bg-well p-0.5"
    >
      <span ref={markerRef} aria-hidden className="seg-plate" />
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) =>
            cn(
              'seg-option relative flex h-[22px] items-center rounded-[3px] px-2 font-mono text-[11px] tracking-[0.04em] whitespace-nowrap uppercase transition-colors focus-visible:-outline-offset-2 max-sm:h-[26px]',
              isActive ? 'text-ink' : 'text-ink-3 hover:text-ink-2',
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
