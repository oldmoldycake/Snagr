import { useEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LogOut, Menu, Plus, Search, User as UserIcon } from 'lucide-react'
import { listCategories } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { cn } from '@/lib/cn'
import { useLogout, useSession } from '@/features/auth/useSession'
import { isRunActive, useRunEvents } from '@/features/runs/RunEventsProvider'
import { RunButton } from '@/features/runs/RunButton'
import { CreateCategoryDialog } from '@/features/categories/CreateCategoryDialog'
import { Input } from '@/components/ui/input'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const NAV_ITEMS: readonly { to: string; label: string; end?: boolean }[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/sites', label: 'Sites' },
  { to: '/runs', label: 'Runs' },
  { to: '/settings', label: 'Settings' },
]

function Wordmark() {
  return (
    <NavLink to="/" className="flex items-baseline gap-1.5">
      <span aria-hidden className="translate-y-px text-[17px] leading-none text-lume">
        ⌖
      </span>
      <span className="font-display text-[22px] leading-none font-bold tracking-[0.1em] text-ink">
        SNAGR
      </span>
    </NavLink>
  )
}

/** Drawer nav for <md — the masthead links plus the category list. */
function MobileNav({ onNavigate }: { onNavigate: () => void }) {
  const { data } = useQuery({ queryKey: qk.categories, queryFn: listCategories })
  const categories = data?.data ?? []

  return (
    <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-4">
      {NAV_ITEMS.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'rounded-sm px-2.5 py-2 font-mono text-xs tracking-[0.11em] text-ink-2 uppercase transition-colors hover:bg-raised hover:text-ink',
              isActive && 'bg-raised text-ink',
            )
          }
        >
          {item.label}
        </NavLink>
      ))}

      <p className="mt-5 mb-1 px-2.5 font-mono text-[10px] font-medium tracking-[0.14em] text-ink-3 uppercase">
        Categories
      </p>
      {categories.map((category) => (
        <NavLink
          key={category.id}
          to={`/categories/${category.slug}`}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              'flex items-center justify-between rounded-sm px-2.5 py-1.5 text-[13px] text-ink-2 transition-colors hover:bg-raised hover:text-ink',
              isActive && 'bg-raised text-ink',
            )
          }
        >
          <span className="truncate">{category.name}</span>
          <span className="flex items-center gap-1.5">
            {category.snagged_count > 0 ? (
              <span title={`${category.snagged_count} at target`} className="font-mono text-xs text-drop">
                ⌖{category.snagged_count}
              </span>
            ) : null}
            <span className="font-mono text-xs text-ink-3 tnum">{category.item_count}</span>
          </span>
        </NavLink>
      ))}
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

export function Masthead() {
  const navigate = useNavigate()
  const { data: user } = useSession()
  const logout = useLogout()
  const { activeRun, setPanelOpen } = useRunEvents()
  const [search, setSearch] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)

  // "/" focuses search from anywhere that isn't already a text field.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== '/' || e.metaKey || e.ctrlKey || e.altKey) return
      const target = e.target as HTMLElement | null
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return
      if (target?.isContentEditable) return
      e.preventDefault()
      searchRef.current?.focus()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const submitSearch = (e: FormEvent) => {
    e.preventDefault()
    const q = search.trim()
    if (q) navigate(`/?search=${encodeURIComponent(q)}`)
  }

  return (
    <header className="shrink-0 border-b border-hairline">
      <div className="mx-auto flex h-14 w-full max-w-[1040px] items-center gap-7 px-6">
        <Sheet open={navOpen} onOpenChange={setNavOpen}>
          <SheetTrigger
            className="-ml-2 flex size-10 shrink-0 items-center justify-center rounded-sm text-ink-2 hover:text-ink md:hidden"
            aria-label="Open navigation"
          >
            <Menu className="size-4" />
          </SheetTrigger>
          <SheetContent side="left" className="max-w-64">
            <SheetTitle className="sr-only">Navigation</SheetTitle>
            <div className="px-4 pt-4 pb-5">
              <Wordmark />
            </div>
            <MobileNav onNavigate={() => setNavOpen(false)} />
          </SheetContent>
        </Sheet>

        <Wordmark />

        <nav className="hidden h-full items-center gap-1 md:flex" aria-label="Main">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  '-mb-px flex h-full items-center border-b-2 border-transparent px-3 font-mono text-[11px] tracking-[0.11em] text-ink-3 uppercase transition-colors hover:text-ink-2',
                  isActive && 'border-lume text-ink hover:text-ink',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <form onSubmit={submitSearch} className="relative hidden w-44 sm:block lg:w-52">
            <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-3" />
            <Input
              ref={searchRef}
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search items…"
              className="h-7 pr-7 pl-8 text-xs"
              aria-label="Search items"
            />
            <kbd
              aria-hidden
              className="pointer-events-none absolute top-1/2 right-2 -translate-y-1/2 rounded-[3px] border border-hairline px-1 font-mono text-[10px] text-ink-3"
            >
              /
            </kbd>
          </form>

          {isRunActive(activeRun) ? (
            <button
              type="button"
              onClick={() => setPanelOpen(true)}
              className="flex items-center gap-1.5 rounded-full border border-lume/40 bg-lume-glow px-2.5 py-1 font-mono text-[11px] tracking-[0.06em] text-lume uppercase hover:bg-lume/20"
            >
              <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-lume" />
              {activeRun?.scope_label ?? 'Running'}
            </button>
          ) : (
            <RunButton scope="global" label="Run all" variant="primary" size="sm" />
          )}

          <DropdownMenu>
            <DropdownMenuTrigger className="flex size-7 items-center justify-center rounded-full border border-hairline-strong bg-raised font-mono text-[11px] text-ink-2 hover:text-ink">
              {user?.email ? (
                user.email[0].toUpperCase()
              ) : (
                <UserIcon className="size-3.5" />
              )}
              <span className="sr-only">Account menu</span>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <div className="px-2 py-1.5 text-xs text-ink-3">{user?.email}</div>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => navigate('/settings')}>
                <UserIcon /> Settings
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => logout.mutate()}>
                <LogOut /> Sign out
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}
