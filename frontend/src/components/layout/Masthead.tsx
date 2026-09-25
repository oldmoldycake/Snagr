import { useEffect, useLayoutEffect, useRef, useState, type FormEvent } from 'react'
import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { LogOut, Menu, Plus, Search, User as UserIcon } from 'lucide-react'
import { listCategories } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { cn } from '@/lib/cn'
import { useInstance, useLogout, useSession } from '@/features/auth/useSession'
import { useJobs } from '@/features/activity/JobsProvider'
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

const NAV_ITEMS: readonly { to: string; label: string; end?: boolean; visionOnly?: boolean }[] = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/sites', label: 'Sites' },
  { to: '/activity', label: 'Activity' },
  { to: '/review', label: 'Review', visionOnly: true },
  { to: '/settings', label: 'Settings' },
]

/** The nav list, with the vision review queue hidden unless the sidecar is configured. */
function useNavItems() {
  const { data: instance } = useInstance()
  return NAV_ITEMS.filter((item) => !item.visionOnly || instance?.vision_enabled)
}

/**
 * Seats the lume bar under the desktop nav's active tab. A navigation animates
 * it (`animate`); the first placement and a re-seat after the tabs change width
 * (fonts loading, the Review tab arriving with the instance) jump instead.
 */
function seatLume(nav: HTMLElement, lume: HTMLElement, animate: boolean) {
  const width = nav.clientWidth
  // below md the tabs are hidden; the resize observer re-seats the bar when they show
  if (width === 0) return
  const placed = lume.style.getPropertyValue('--l') !== ''
  const tab = nav.querySelector<HTMLElement>('a[aria-current="page"]')
  const place = (left: number, right: number) => {
    lume.style.setProperty('--l', `${left}px`)
    lume.style.setProperty('--r', `${right}px`)
  }
  const instantly = (move: () => void) => {
    lume.dataset.instant = ''
    move()
    void lume.offsetWidth // commit the jump, so restoring transitions doesn't replay it
    delete lume.dataset.instant
  }

  // item and category pages have no tab: the bar folds into its own center and fades
  if (!tab) {
    if (animate && placed && lume.dataset.state !== 'idle') {
      const center = lume.offsetLeft + lume.offsetWidth / 2
      delete lume.dataset.dir
      place(center, width - center)
    }
    lume.dataset.state = 'idle'
    return
  }

  const left = tab.offsetLeft
  const right = width - left - tab.offsetWidth
  const wasIdle = lume.dataset.state === 'idle'
  delete lume.dataset.state
  if (!animate || !placed) {
    instantly(() => place(left, right))
  } else if (wasIdle) {
    // grow out of the new tab rather than slide in from wherever the bar was hidden
    const center = left + tab.offsetWidth / 2
    delete lume.dataset.dir
    instantly(() => place(center, width - center))
    place(left, right)
  } else {
    // the edge nearest the new tab leads and the other catches up
    lume.dataset.dir = left > lume.offsetLeft ? 'right' : 'left'
    place(left, right)
  }
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
 * Top bar of every signed-in page: navigation, item search, the live-job
 * indicator that opens the activity sheet, and the account menu.
 */
export function Masthead() {
  const navigate = useNavigate()
  const { data: user } = useSession()
  const logout = useLogout()
  const { live, setPanelOpen } = useJobs()
  const [search, setSearch] = useState('')
  const [navOpen, setNavOpen] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)
  const navRef = useRef<HTMLElement>(null)
  const lumeRef = useRef<HTMLSpanElement>(null)
  const navItems = useNavItems()
  const { pathname } = useLocation()

  // runs after NavLink has committed the new aria-current
  useLayoutEffect(() => {
    if (navRef.current && lumeRef.current) seatLume(navRef.current, lumeRef.current, true)
  }, [pathname])

  useEffect(() => {
    const nav = navRef.current
    const lume = lumeRef.current
    if (!nav || !lume) return
    const ro = new ResizeObserver(() => seatLume(nav, lume, false))
    ro.observe(nav)
    return () => ro.disconnect()
  }, [])

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
