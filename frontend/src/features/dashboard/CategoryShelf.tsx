import { useEffect, useLayoutEffect, useRef, type CSSProperties } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, Globe, MoreHorizontal, Pencil, Search } from 'lucide-react'
import type { Category, PriceDrop } from '@/api/types'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn } from '@/lib/cn'
import { useJobs } from '@/features/activity/JobsProvider'
import { AddItemDialog } from '@/features/items/AddItemDialog'
import { WatchList } from '@/features/items/WatchList'
import type { Lead, Shelf } from './shelves'

/** How long rows keep their drop-in after a user opens a shelf. */
const ROWS_IN_MS = 460
/** Hides a closed body even if its transition was interrupted and never ended. */
const CLOSE_FALLBACK_MS = 260

const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`

/**
 * One category on the dashboard: a header that toggles, then the sites it
 * searches, the caller's items in it and a link to its page. Collapsed, the
 * header's lead line stands in for the rows.
 */
export function CategoryShelf({
  shelf,
  siteNames,
  open,
  onToggle,
  total,
  drops,
  struck,
  edge,
  openDelay = 0,
  onEditSites,
  onRename,
}: {
  shelf: Shelf
  siteNames: string[]
  open: boolean
  /** omitted while a search forces every shelf open */
  onToggle?: (open: boolean) => void
  /** while searching: how many of the caller's items the shelf holds, of which `shelf.items` match */
  total?: number
  drops?: Map<number, PriceDrop>
  struck?: Set<number>
  /** outline it once (just revealed, or a strike reopened it); a shelf that mounts this way opens on the next frame */
  edge?: boolean
  /** Expand all opens shelves in a cascade, each a little after the one above */
  openDelay?: number
  onEditSites: (category: Category) => void
  onRename: (category: Category) => void
}) {
  const { category, items, hits, lead } = shelf
  const navigate = useNavigate()
  const { enqueue } = useJobs()
  const sectionRef = useRef<HTMLElement>(null)
  const bodyRef = useRef<HTMLDivElement>(null)
  const mounted = useRef(false)
  // how the next open was asked for: by this shelf's toggle (rows drop in) or by Ctrl-F (no motion)
  const openedBy = useRef<'toggle' | 'find' | null>(null)
  // edge and openDelay only shape how an open plays, so the effect below reads
  // their latest values without re-running (and replaying the open) when they change
  const motion = useRef({ edge, openDelay })
  useLayoutEffect(() => {
    motion.current = { edge, openDelay }
  })

  const noSites = category.site_ids.length === 0
  const bodyId = `shelf-${category.id}-body`
  const headingId = `shelf-${category.id}-h`

  // data-state and the body's hidden="until-found" are set here rather than in
  // JSX so each step lands in order: a closing body can't take `hidden` until
  // its height has animated away, because hidden collapses it at once.
  useLayoutEffect(() => {
    const section = sectionRef.current
    const body = bodyRef.current
    if (!section || !body) return
    const timers: number[] = []
    let frame = 0

    const setClosed = () => {
      section.dataset.state = 'closed'
      body.setAttribute('hidden', 'until-found')
    }
    const setOpen = (rowsIn: boolean) => {
      body.removeAttribute('hidden')
      void body.offsetHeight // commit the closed layout, so the rows transition from it
      section.dataset.state = 'open'
      if (rowsIn) {
        section.dataset.rowsIn = ''
        timers.push(window.setTimeout(() => delete section.dataset.rowsIn, ROWS_IN_MS))
      }
    }

    const { edge: revealed, openDelay: delay } = motion.current
    if (!mounted.current) {
      mounted.current = true
      if (!open) setClosed()
      else if (revealed) {
        setClosed()
        frame = requestAnimationFrame(() => setOpen(true))
      } else section.dataset.state = 'open'
      return () => cancelAnimationFrame(frame)
    }

    const by = openedBy.current
    openedBy.current = null
    const hide = () => {
      if (section.dataset.state === 'closed') body.setAttribute('hidden', 'until-found')
    }
    const onEnd = (e: TransitionEvent) => {
      if (e.target === body && e.propertyName === 'grid-template-rows') hide()
    }

    if (open) {
      if (by === 'find') {
        section.dataset.instant = ''
        setOpen(false)
        frame = requestAnimationFrame(() => delete section.dataset.instant)
      } else if (delay > 0) {
        timers.push(window.setTimeout(() => setOpen(false), delay))
      } else {
        setOpen(by === 'toggle')
      }
    } else {
      delete section.dataset.rowsIn
      section.dataset.state = 'closed'
      body.addEventListener('transitionend', onEnd)
      timers.push(window.setTimeout(hide, CLOSE_FALLBACK_MS))
    }
    return () => {
      timers.forEach((t) => window.clearTimeout(t))
      cancelAnimationFrame(frame)
      body.removeEventListener('transitionend', onEnd)
    }
  }, [open])

  // Ctrl-F matched a row in the collapsed body: open the shelf. React has no
  // onBeforeMatch, so the listener goes on through the ref.
  useEffect(() => {
    const body = bodyRef.current
    if (!body || !onToggle) return
    const onBeforeMatch = () => {
      openedBy.current = 'find'
      onToggle(true)
    }
    body.addEventListener('beforematch', onBeforeMatch)
    return () => body.removeEventListener('beforematch', onBeforeMatch)
  }, [onToggle])

  return (
    <section
      ref={sectionRef}
      id={`shelf-${category.id}`}
      data-edge={edge || undefined}
      className="shelf scroll-mt-11 overflow-clip rounded-md border border-hairline bg-surface data-edge:animate-strike-edge"
    >
      <div className="shelf-head flex min-h-12 items-center gap-2 pr-2.5">
        <h3 id={headingId} className="min-w-0 flex-1">
          <button
            type="button"
            aria-expanded={open}
            aria-controls={bodyId}
            onClick={() => {
              if (!onToggle) return
              openedBy.current = 'toggle'
              onToggle(!open)
            }}
            className="shelf-toggle flex min-h-12 w-full flex-wrap items-center gap-x-3 gap-y-1 rounded-l-md py-2 pr-2 pl-3 text-left focus-visible:-outline-offset-2"
          >
            <svg viewBox="0 0 10 10" aria-hidden className="shelf-chevron size-3.5 shrink-0">
              <path d="M3.5 1.5 7 5l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
            </svg>
            <span className="font-display text-[19px] leading-none font-semibold tracking-[0.06em] text-ink uppercase">
              {category.name}
            </span>
            <span className="font-mono text-[11px] text-ink-3 tnum">
              {total != null ? `${items.length} of ${total} match` : plural(items.length, 'item', 'items')}
            </span>
            {hits > 0 ? <span className="font-mono text-[11px] text-drop tnum">⌖ {hits} in range</span> : null}
            <LeadLine lead={lead} />
            <span className="flex-1 max-sm:hidden" />
            <span
              className={cn(
                'shelf-peek font-mono text-[11px] tnum max-sm:hidden',
                noSites ? 'text-warn' : 'text-ink-3',
              )}
            >
              {noSites ? '⚠ no sites' : plural(category.site_ids.length, 'site', 'sites')}
            </span>
          </button>
        </h3>
        <div className="flex shrink-0 items-center gap-1">
          {noSites ? (
            <Button variant="warn" size="sm" onClick={() => onEditSites(category)}>
              Link sites
            </Button>
          ) : (
            <AddItemDialog
              categoryId={category.id}
              categoryName={category.name}
              variant="default"
              label={`Add item to ${category.name}`}
              className="max-sm:size-9 max-sm:px-0 max-sm:text-base"
              trigger={
                <>
                  <span className="max-sm:hidden">＋ Add item</span>
                  <span aria-hidden className="sm:hidden">
                    ＋
                  </span>
                </>
              }
            />
          )}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="iconSm" aria-label={`More for ${category.name}`}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem
                disabled={noSites}
                onSelect={() => enqueue({ kind: 'hunt', scope: 'category', scope_id: category.id })}
              >
                <Search /> Hunt now
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onEditSites(category)}>
                <Globe /> Edit sites
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onRename(category)}>
                <Pencil /> Rename
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => navigate(`/categories/${category.slug}`)}>
                <ArrowRight /> Open category page
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      <div ref={bodyRef} id={bodyId} role="region" aria-labelledby={headingId} className="shelf-body">
        <div className="shelf-inner">
          {noSites ? (
            <div
              style={{ '--i': 0 } as CSSProperties}
              className="shelf-stagger flex items-center gap-3 border-t border-warn/25 bg-warn/10 px-3.5 py-[9px] text-[13px] text-warn"
            >
              <span aria-hidden>⚠</span>
              <span>
                No sites linked. The hunter can't search for{' '}
                {items.length === 1 ? 'this item' : `these ${items.length} items`}.
              </span>
            </div>
          ) : (
            <button
              type="button"
              aria-label={`Edit sites for ${category.name}`}
              onClick={() => onEditSites(category)}
              style={{ '--i': 0 } as CSSProperties}
              className="shelf-stagger group/sites mb-2.5 ml-[38px] inline-flex flex-wrap items-center gap-[5px] rounded-sm px-1.5 py-[3px] font-mono text-[11px] text-ink-2 transition-colors hover:bg-raised max-sm:ml-[26px]"
            >
              <span className="mr-0.5 text-[9.5px] tracking-[0.14em] text-ink-3 uppercase">Searching</span>
              {siteNames.map((name) => (
                <span
                  key={name}
                  className="inline-flex h-[19px] items-center rounded-[3px] border border-hairline bg-raised px-1.5"
                >
                  {name}
                </span>
              ))}
              <span className="ml-1 text-[10px] tracking-[0.08em] text-ink-3 uppercase group-hover/sites:text-lume">
                edit
              </span>
            </button>
          )}
          <div className="border-t border-hairline">
            <WatchList items={items} drops={drops} struck={struck} showSite hideHeader fixedColumns />
          </div>
          <div
            style={{ '--i': 5 } as CSSProperties}
            className="shelf-stagger flex flex-wrap gap-x-3 gap-y-1 border-t border-hairline bg-well px-3.5 py-[7px] font-mono text-[11px] text-ink-3"
          >
            <span className="tnum">{plural(total ?? items.length, 'item', 'items')} · closest first</span>
            <span className="flex-1" />
            <Link to={`/categories/${category.slug}`} className="text-ink-2 hover:text-lume">
              Open {category.name} →
            </Link>
          </div>
        </div>
      </div>
    </section>
  )
}

/** The collapsed shelf's one line; it fades while the shelf is open but keeps its space. */
function LeadLine({ lead }: { lead: Lead }) {
  // on a phone the lead wraps onto its own line instead (see .shelf-lead in globals.css)
  const base = 'shelf-peek shelf-lead min-w-0 sm:truncate'
  switch (lead.kind) {
    case 'hit':
      return (
        <span className={cn(base, 'font-mono text-[11.5px] text-drop')}>
          ⌖ {lead.name} at {lead.amount}
        </span>
      )
    case 'closest':
      return (
        <span className={cn(base, 'text-[12.5px] text-ink-2')}>
          {lead.name} · <span className="font-mono text-xs font-semibold text-lume tnum">{lead.amount}</span> from
          striking
        </span>
      )
    case 'priced':
      return (
        <span className={cn(base, 'text-[12.5px] text-ink-2')}>
          {lead.name} at <span className="font-mono text-xs text-ink tnum">{lead.amount}</span>
        </span>
      )
    case 'idle':
      return <span className={cn(base, 'font-mono text-[11px] text-ink-3')}>hunting · no prices yet</span>
  }
}
