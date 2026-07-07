import type { ReactNode } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity, Globe, LayoutDashboard, Plus, Settings } from 'lucide-react'
import { listCategories } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { cn } from '@/lib/cn'
import { CreateCategoryDialog } from '@/features/categories/CreateCategoryDialog'

function NavItem({
  to,
  icon,
  label,
  end,
  onClick,
}: {
  to: string
  icon: ReactNode
  label: string
  end?: boolean
  onClick?: () => void
}) {
  return (
    <NavLink
      to={to}
      end={end}
      onClick={onClick}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 rounded-sm px-2.5 py-1.5 text-[13px] text-ink-2 transition-colors',
          'hover:bg-raised hover:text-ink',
          isActive && 'bg-raised text-ink',
        )
      }
    >
      <span className="[&_svg]:size-4 [&_svg]:text-ink-3">{icon}</span>
      {label}
    </NavLink>
  )
}

export function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const location = useLocation()
  const { data } = useQuery({ queryKey: qk.categories, queryFn: listCategories })
  const categories = data?.data ?? []

  return (
    <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-4">
      <NavItem to="/" end icon={<LayoutDashboard />} label="Dashboard" onClick={onNavigate} />
      <NavItem to="/sites" icon={<Globe />} label="Sites" onClick={onNavigate} />
      <NavItem to="/runs" icon={<Activity />} label="Runs" onClick={onNavigate} />
      <NavItem to="/settings" icon={<Settings />} label="Settings" onClick={onNavigate} />

      <p className="mt-5 mb-1 px-2.5 text-[11px] font-medium tracking-wide text-ink-3 uppercase">
        Categories
      </p>
      {categories.map((category) => {
        const to = `/categories/${category.slug}`
        const isActive = location.pathname === to
        return (
          <NavLink
            key={category.id}
            to={to}
            onClick={onNavigate}
            className={cn(
              'flex items-center justify-between rounded-sm px-2.5 py-1.5 text-[13px] text-ink-2 transition-colors hover:bg-raised hover:text-ink',
              isActive && 'bg-raised text-ink',
            )}
          >
            <span className="truncate">{category.name}</span>
            <span className="flex items-center gap-1.5">
              {category.snagged_count > 0 ? (
                <span title={`${category.snagged_count} at target`} className="text-xs text-drop">
                  ⌖{category.snagged_count}
                </span>
              ) : null}
              <span className="font-mono text-xs text-ink-3 tnum">{category.item_count}</span>
            </span>
          </NavLink>
        )
      })}
      {/* No onNavigate here: closing the drawer would unmount this dialog before it opens. */}
      <CreateCategoryDialog
        variant="ghost"
        className="mt-1 justify-start px-2.5 text-ink-3"
        trigger={
          <span className="inline-flex items-center gap-2">
            <Plus className="size-3.5" /> New category
          </span>
        }
      />
    </nav>
  )
}

export function Sidebar() {
  return (
    <aside className="hidden w-52 shrink-0 flex-col border-r border-hairline bg-surface md:flex">
      <NavLink to="/" className="flex items-center gap-2 px-4 pt-4 pb-5">
        <span aria-hidden className="text-lg leading-none text-drop">
          ⌖
        </span>
        <span className="font-display text-[15px] font-bold tracking-wide text-ink">SNAGR</span>
      </NavLink>

      <SidebarNav />
    </aside>
  )
}
