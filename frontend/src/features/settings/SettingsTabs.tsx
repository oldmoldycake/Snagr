import { NavLink } from 'react-router-dom'
import { cn } from '@/lib/cn'
import { useInstance, useSession } from '@/features/auth/useSession'

/**
 * The settings sub-navigation — one route per tab, styled as the Segmented
 * control's routed twin so the page reads as one system. Tabs the viewer can't
 * use drop out (Users is admin-only; MCP & API goes when the operator turned
 * agent access off), the way the vision link drops out of the masthead.
 */
export function SettingsTabs() {
  const { data: user } = useSession()
  const { data: instance } = useInstance()

  const tabs: { to: string; label: string; end?: boolean }[] = [
    { to: '/settings', label: 'General', end: true },
  ]
  if (instance?.mcp_enabled) tabs.push({ to: '/settings/api', label: 'MCP & API' })
  if (user?.role === 'admin') tabs.push({ to: '/settings/users', label: 'Users' })

  return (
    <nav aria-label="Settings sections" className="inline-flex gap-0.5">
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end={tab.end}
          className={({ isActive }) =>
            cn(
              'rounded-sm px-2 py-1 font-mono text-[11px] tracking-[0.04em] uppercase transition-colors',
              isActive ? 'bg-lume-glow text-lume' : 'text-ink-3 hover:text-ink-2',
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
