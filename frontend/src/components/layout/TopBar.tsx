import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { LogOut, Search, User as UserIcon } from 'lucide-react'
import { useLogout, useSession } from '@/features/auth/useSession'
import { isRunActive, useRunEvents } from '@/features/runs/RunEventsProvider'
import { RunButton } from '@/features/runs/RunButton'
import { Input } from '@/components/ui/input'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export function TopBar() {
  const navigate = useNavigate()
  const { data: user } = useSession()
  const logout = useLogout()
  const { activeRun, setPanelOpen } = useRunEvents()
  const [search, setSearch] = useState('')

  const submitSearch = (e: FormEvent) => {
    e.preventDefault()
    const q = search.trim()
    if (q) navigate(`/?search=${encodeURIComponent(q)}`)
  }

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b border-hairline bg-surface px-4">
      <form onSubmit={submitSearch} className="relative w-full max-w-64">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-ink-3" />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search items…"
          className="h-7 pl-8 text-xs"
          aria-label="Search items"
        />
      </form>

      <div className="ml-auto flex items-center gap-2">
        {isRunActive(activeRun) ? (
          <button
            type="button"
            onClick={() => setPanelOpen(true)}
            className="flex items-center gap-1.5 rounded-full border border-accent/40 bg-accent/10 px-2.5 py-1 text-xs text-accent hover:bg-accent/20"
          >
            <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-accent" />
            {activeRun?.scope_label ?? 'Running'}
          </button>
        ) : (
          <RunButton scope="global" label="Run all" variant="snag" size="sm" />
        )}

        <DropdownMenu>
          <DropdownMenuTrigger className="flex size-7 items-center justify-center rounded-full border border-hairline bg-raised text-ink-2 hover:text-ink">
            <UserIcon className="size-3.5" />
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
    </header>
  )
}
