import { useEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, KeyRound, LogOut, Menu, Plus, Search, SlidersHorizontal, User as UserIcon, Users } from 'lucide-react'
import { getJobsSummary, listCategories } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { cn } from '@/lib/cn'
import { countdown } from '@/lib/time'
import { useTrack } from '@/lib/useTrack'
import { useInstance, useLogout, useSession } from '@/features/auth/useSession'
import { useJobs } from '@/features/activity/JobsProvider'
import { CreateCategoryDialog } from '@/features/categories/CreateCategoryDialog'
import { Input } from '@/components/ui/input'
import { Radar } from '@/components/ui/radar'
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuHint,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const NAV_ITEMS: readonly { to: string; label: string; end?: boolean; visionOnly?: boolean }[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/sites', label: 'Sites' },
  { to: '/activity', label: 'Activity' },
  { to: '/review', label: 'Photo review', visionOnly: true },
  { to: '/settings', label: 'Settings' },
]

/** The nav list, with the vision review queue hidden unless the sidecar is configured. */
function useNavItems() {
  const { data: instance } = useInstance()
  return NAV_ITEMS.filter((item) => !item.visionOnly || instance?.vision_enabled)
}

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

function MobileNav({ onNavigate }: { onNavigate: () => void }) {
  const { data } = useQuery({ queryKey: qk.categories, queryFn: listCategories })
  const categories = data?.data ?? []
  const navItems = useNavItems()

  return (
    <nav className="flex flex-1 flex-col gap-0.5 overflow-y-auto px-2 pb-4">
      {navItems.map((item) => (
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

/**
 * The avatar's menu: who is signed in, what the hunter is doing, the settings
 * tabs the viewer can use (SettingsTabs' rules), and sign out. The jobs summary
 * is fetched only while the menu is open.
 */
function AccountMenu() {
  const navigate = useNavigate()
  const { data: user } = useSession()
  const { data: instance } = useInstance()
  const logout = useLogout()
  const { live, setPanelOpen } = useJobs()
  const [open, setOpen] = useState(false)
  const summary = useQuery({ queryKey: qk.jobsSummary, queryFn: getJobsSummary, enabled: open })

  const checksRunning = summary.data?.checks_running ?? 0
  const hunts = live.filter((job) => job.kind === 'hunt').length
  let status: string
  if (hunts > 0) status = `${hunts} ${hunts === 1 ? 'hunt' : 'hunts'} running`
  else if (checksRunning > 0) status = `checking · ${checksRunning} live`
  else if (instance?.hunt_enabled === false) status = 'Hunting is off on this server · prices are still checked'
  else if (summary.data?.next_check_at) status = `idle · next check ${countdown(summary.data.next_check_at)}`
  else status = 'idle'

  return (
    <DropdownMenu open={open} onOpenChange={setOpen}>
      <DropdownMenuTrigger className="relative flex size-7 items-center justify-center rounded-full border border-hairline-strong bg-raised font-mono text-[11px] text-ink-2 transition-colors hover:text-ink data-[state=open]:border-lume data-[state=open]:bg-lume-glow data-[state=open]:text-lume">
        {user?.email ? user.email[0].toUpperCase() : <UserIcon className="size-3.5" />}
        <span className="sr-only">Account menu</span>
        <svg viewBox="0 0 40 40" aria-hidden className="avatar-ticks size-10">
          <path d="M20 1.5v4M38.5 20h-4M20 38.5v-4M1.5 20h4" />
        </svg>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-[272px]">
        <DropdownMenuLabel className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid size-[30px] shrink-0 place-items-center rounded-full border border-lume bg-lume-glow font-mono text-xs text-lume"
          >
            {user?.email ? user.email[0].toUpperCase() : null}
          </span>
          <span className="grid min-w-0 gap-px">
            <span className="font-mono text-[9.5px] tracking-[0.16em] text-ink-3 uppercase">Signed in as</span>
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-[13px] text-ink">{user?.email}</span>
              {user?.role === 'admin' ? (
                <span className="rounded-[3px] border border-hairline-strong px-[5px] font-mono text-[9.5px] leading-[15px] font-medium tracking-[0.12em] text-ink-2 uppercase">
                  Admin
                </span>
              ) : null}
            </span>
          </span>
        </DropdownMenuLabel>
        <DropdownMenuItem onSelect={() => setPanelOpen(true)}>
          <Radar size={16} animate={hunts + checksRunning > 0} />
          <span className="grid min-w-0 flex-1 gap-px">
            <span>Activity</span>
            <span className={cn('font-mono text-[10.5px]', hunts + checksRunning > 0 ? 'text-lume' : 'text-ink-3')}>
              {status}
            </span>
          </span>
          <ChevronRight />
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate('/settings')}>
          <SlidersHorizontal /> Settings
          <DropdownMenuHint>general</DropdownMenuHint>
        </DropdownMenuItem>
        {instance?.mcp_enabled ? (
          <DropdownMenuItem onSelect={() => navigate('/settings/api')}>
            <KeyRound /> MCP &amp; API
            <DropdownMenuHint>tokens</DropdownMenuHint>
          </DropdownMenuItem>
        ) : null}
        {user?.role === 'admin' ? (
          <DropdownMenuItem onSelect={() => navigate('/settings/users')}>
            <Users /> Users
            <DropdownMenuHint>invites</DropdownMenuHint>
          </DropdownMenuItem>
        ) : null}
        <div className="-mx-1 mt-1 -mb-1 grid border-t border-hairline bg-well p-1">
          <DropdownMenuItem onSelect={() => logout.mutate()}>
            <LogOut /> Sign out
            {instance ? <DropdownMenuHint>v{instance.version}</DropdownMenuHint> : null}
          </DropdownMenuItem>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

/**
 * Top bar of every signed-in page: navigation, item search, the live-job
 * indicator that opens the activity sheet, and the account menu.
 */
export function Masthead() {
  const navigate = useNavigate()
  const { live, setPanelOpen } = useJobs()
  const [search, setSearch] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const navItems = useNavItems()
  const { pathname } = useLocation()
  // item and category pages have no tab: the bar folds away
  const { hostRef: navRef, markerRef: lumeRef } = useTrack<HTMLElement>('a[aria-current="page"]', pathname)

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

        <nav ref={navRef} className="relative hidden h-full items-center gap-1 md:flex" aria-label="Main">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                cn(
                  'nav-tab relative flex h-full items-center px-3 font-mono text-[11px] tracking-[0.11em] text-ink-3 uppercase transition-colors hover:text-ink-2 focus-visible:-outline-offset-2',
                  isActive && 'text-ink hover:text-ink',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
          <span ref={lumeRef} aria-hidden className="nav-lume" />
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

          {/* the only masthead state: a pill while something is running.
              There is no button — the hunter is already hunting. */}
          {live.length > 0 ? (
            <button
              type="button"
              onClick={() => setPanelOpen(true)}
              className="flex items-center gap-1.5 rounded-full border border-lume/40 bg-lume-glow px-2.5 py-1 font-mono text-[11px] tracking-[0.06em] text-lume uppercase hover:bg-lume/20"
            >
              <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-lume" />
              {live.length} {live.length === 1 ? 'hunt' : 'hunts'}
            </button>
          ) : null}

          <AccountMenu />
        </div>
      </div>
    </header>
  )
}
