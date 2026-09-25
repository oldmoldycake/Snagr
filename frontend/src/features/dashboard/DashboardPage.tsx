import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { getPriceDrops, listCategories, listItems, listSites } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { Category, ItemSummary, PriceDrop } from '@/api/types'
import { RangeSelector, useRangeParam } from '@/components/charts/RangeSelector'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/ui/error-state'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { useMediaQuery } from '@/lib/useMediaQuery'
import { HunterTicker } from '@/features/activity/HunterTicker'
import { useSession } from '@/features/auth/useSession'
import { CreateCategoryDialog } from '@/features/categories/CreateCategoryDialog'
import { EditCategoryDialog } from '@/features/categories/EditCategoryDialog'
import { EditSitesDialog } from '@/features/categories/EditSitesDialog'
import { WatchListLabels } from '@/features/items/WatchList'
import { CategoryRow } from './CategoryRow'
import { CategoryShelf } from './CategoryShelf'
import { GuideHero, type GuideState } from './GuideHero'
import { defaultOpen, groupShelves, newlyStruck, resolveOpen, type StoredShelf } from './shelves'
import { useShelfState } from './useShelfState'
import { VerdictHero } from './VerdictHero'

/** One page of everything: the self-hosted watch fits in a single fetch. */
const WATCH_PAGE_SIZE = 200
/** Rows of categories holding none of your items, before "＋ N more categories". */
const ROWS_SHOWN = 5
/** How long a struck row flashes, and how long a shelf or row keeps its outline. */
const CUE_MS = 1300
/** Under reduced motion the struck row gets a static edge instead of a flash, so it stays longer. */
const CUE_REDUCED_MS = 8000
/** Expand all opens shelf i after min(i, 4) steps, top to bottom. */
const CASCADE_STEP_MS = 40
const CASCADE_MAX_STEPS = 4

/** A dialog opened for one category from a shelf or row, remounted fresh on each open. */
type CategoryDialog = { category: Category; open: boolean; session: number }

/**
 * Home page. With items: the verdict hero, the hunter ticker, then one shelf
 * per category you track something in, most urgent first, and one line for
 * each category you don't. Without: a guide hero that walks you to your first
 * category and item.
 */
export function DashboardPage() {
  const [range, setRange] = useRangeParam()
  const [params] = useSearchParams()
  const search = params.get('search') || undefined
  const reducedMotion = useMediaQuery('(prefers-reduced-motion: reduce)')
  const userId = useSession().data?.id ?? null

  const drops = useQuery({
    queryKey: qk.dashboardDrops(range),
    queryFn: () => getPriceDrops(range, 20),
    placeholderData: keepPreviousData,
  })
  const items = useQuery({
    queryKey: qk.items({ range, per_page: WATCH_PAGE_SIZE }),
    queryFn: () => listItems({ range, per_page: WATCH_PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  // the unfiltered list above stays loaded during a search: it gives each shelf its "of N"
  const matches = useQuery({
    queryKey: qk.items({ range, search, per_page: WATCH_PAGE_SIZE }),
    queryFn: () => listItems({ range, search, per_page: WATCH_PAGE_SIZE }),
    enabled: search != null,
    placeholderData: keepPreviousData,
  })
  const categories = useQuery({ queryKey: qk.categories, queryFn: listCategories })
  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })

  const [justCreatedId, setJustCreatedId] = useState<number | null>(null)
  const [showAllRows, setShowAllRows] = useState(false)
  const [cascading, setCascading] = useState(false)
  const [struckIds, setStruckIds] = useState<Set<number>>(new Set())
  const [edgeIds, setEdgeIds] = useState<Set<number>>(new Set())
  const [sitesDialog, setSitesDialog] = useState<CategoryDialog | null>(null)
  const [renameDialog, setRenameDialog] = useState<CategoryDialog | null>(null)
  // a row or shelf the user just made appear; scrolled to once it renders
  const scrollTarget = useRef<number | null>(null)
  // collapse state is neither read nor written while a search forces every shelf open
  const { stored, write } = useShelfState(search ? null : userId)

  const myItems = useMemo(() => items.data?.data ?? [], [items.data])
  const categoryList = useMemo(() => categories.data?.data ?? [], [categories.data])
  const liveIds = useMemo(() => new Set(categoryList.map((c) => c.id)), [categoryList])
  const { shelves, rows } = useMemo(
    () => groupShelves(myItems, categoryList, justCreatedId),
    [myItems, categoryList, justCreatedId],
  )
  const defaults = useMemo(() => defaultOpen(shelves), [shelves])
  const resolved = shelves.map((shelf) => resolveOpen(stored.get(shelf.category.id), shelf, defaults))
  const dropsByItem = useMemo(() => {
    const map = new Map<number, PriceDrop>()
    for (const drop of drops.data?.data ?? []) {
      // the endpoint returns drops newest-first, so the first per item wins
      if (!map.has(drop.item_id)) map.set(drop.item_id, drop)
    }
    return map
  }, [drops.data])
  const siteNamesOf = (category: Category) =>
    (sites.data?.data ?? []).filter((s) => category.site_ids.includes(s.id)).map((s) => s.name)

  // Strikes: items in range now that weren't in the previous response (the
  // SSE provider refetches items as jobs finish). Tracked during render, not in
  // an effect, so the flash lands in the same frame as the new rows.
  const [seen, setSeen] = useState<{ data: unknown; inRange: Set<number> | null }>({ data: null, inRange: null })
  if (items.data && items.data !== seen.data) {
    const struck = newlyStruck(seen.inRange, myItems)
    setSeen({ data: items.data, inRange: new Set(myItems.filter((i) => i.target_met).map((i) => i.id)) })
    if (struck.length > 0) setStruckIds(new Set(struck))
  }

  // A stored collapse loses to a new strike: store the shelf as open again and outline it.
  const reopened = shelves.filter((_, i) => resolved[i].reopened)
  if (reopened.length > 0 && !search) {
    write(
      new Map(reopened.map((s): [number, StoredShelf] => [s.category.id, { collapsed: false, snaggedAt: s.hits }])),
      liveIds,
    )
    setEdgeIds((prev) => new Set([...prev, ...reopened.map((s) => s.category.id)]))
  }

  useEffect(() => {
    if (struckIds.size === 0) return
    const t = window.setTimeout(() => setStruckIds(new Set()), reducedMotion ? CUE_REDUCED_MS : CUE_MS)
    return () => window.clearTimeout(t)
  }, [struckIds, reducedMotion])

  useEffect(() => {
    if (edgeIds.size === 0) return
    const t = window.setTimeout(() => setEdgeIds(new Set()), CUE_MS)
    return () => window.clearTimeout(t)
  }, [edgeIds])

  // Scroll to what the user just asked for, once it exists. Never for a strike:
  // that would pull the page out from under someone reading it.
  useEffect(() => {
    const id = scrollTarget.current
    if (id == null) return
    const el = document.getElementById(`shelf-${id}`)
    if (!el) return
    scrollTarget.current = null
    el.scrollIntoView({ block: 'nearest', behavior: reducedMotion ? 'auto' : 'smooth' })
  })

  const reveal = (categoryId: number) => {
    setEdgeIds((prev) => new Set([...prev, categoryId]))
    scrollTarget.current = categoryId
  }
  const onCreated = (category: Category) => {
    setJustCreatedId(category.id)
    reveal(category.id)
  }
  const onAdded = (item: ItemSummary) => {
    write(new Map([[item.category_id, { collapsed: false, snaggedAt: 0 }]]), liveIds)
    reveal(item.category_id)
  }
  const toggle = (index: number, open: boolean) => {
    const shelf = shelves[index]
    write(new Map([[shelf.category.id, { collapsed: !open, snaggedAt: shelf.hits }]]), liveIds)
  }
  const anyOpen = resolved.some((r) => r.open)
  const toggleAll = () => {
    const open = !anyOpen
    write(
      new Map(shelves.map((s): [number, StoredShelf] => [s.category.id, { collapsed: !open, snaggedAt: s.hits }])),
      liveIds,
    )
    if (open) {
      setCascading(true)
      window.setTimeout(() => setCascading(false), (CASCADE_MAX_STEPS + 1) * CASCADE_STEP_MS + 200)
    }
  }
  const openSites = (category: Category) =>
    setSitesDialog((prev) => ({ category, open: true, session: (prev?.session ?? 0) + 1 }))
  const openRename = (category: Category) =>
    setRenameDialog((prev) => ({ category, open: true, session: (prev?.session ?? 0) + 1 }))

  const dialogs = (
    <>
      {sitesDialog ? (
        <EditSitesDialog
          key={`sites-${sitesDialog.session}`}
          category={sitesDialog.category}
          open={sitesDialog.open}
          onOpenChange={(open) => setSitesDialog((prev) => prev && { ...prev, open })}
        />
      ) : null}
      {renameDialog ? (
        <EditCategoryDialog
          key={`rename-${renameDialog.session}`}
          category={renameDialog.category}
          open={renameDialog.open}
          onOpenChange={(open) => setRenameDialog((prev) => prev && { ...prev, open })}
          // renaming from a shelf stays on the dashboard
          onSaved={() => undefined}
        />
      ) : null}
    </>
  )

  if (search) {
    const failed = matches.isError ? matches : categories.isError ? categories : null
    return (
      <div>
        <SearchResults
          search={search}
          matches={matches.data?.data}
          myItems={myItems}
          categories={categoryList}
          loading={matches.isLoading || categories.isLoading}
          error={
            failed ? (
              <ErrorState
                title="Couldn't search your shelves"
                error={failed.error}
                onRetry={() => void failed.refetch()}
                retrying={failed.isFetching}
              />
            ) : null
          }
          siteNamesOf={siteNamesOf}
          drops={dropsByItem}
          onEditSites={openSites}
          onRename={openRename}
        />
        {dialogs}
      </div>
    )
  }

  if (items.isLoading || categories.isLoading) {
    return (
      <div>
        <div className="space-y-3">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-8 w-60" />
          <Skeleton className="h-5 w-96" />
        </div>
        <div className="mt-[62px] space-y-2.5">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      </div>
    )
  }

  // the guide and the shelves both say what exists, so neither may stand in for a failed load
  const failed = items.isError ? items : categories.isError ? categories : null
  if (failed) {
    return (
      <ErrorState
        title="Couldn't load your watch"
        error={failed.error}
        onRetry={() => void failed.refetch()}
        retrying={failed.isFetching}
      />
    )
  }

  if (myItems.length === 0) {
    const justCreated = categoryList.find((c) => c.id === justCreatedId)
    const guide: GuideState = justCreated
      ? { kind: 'ready', category: justCreated, siteNames: siteNamesOf(justCreated) }
      : categoryList.length > 0
        ? { kind: 'shared', categoryCount: categoryList.length }
        : { kind: 'empty' }
    return (
      <div>
        <GuideHero state={guide} onCreated={onCreated} onAdded={onAdded} />
        {categoryList.length > 0 ? (
          <section className="mt-[26px]">
            <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3.5 gap-y-2">
              <h2 className="font-display text-[19px] font-semibold tracking-[0.12em] text-ink-2 uppercase">
                Categories
              </h2>
              <span className="font-mono text-[11px] text-ink-3 tnum">{categoryList.length} on this instance</span>
              <span className="flex-1" />
              {justCreated ? (
                <CreateCategoryDialog variant="default" trigger="＋ New category" onCreated={onCreated} />
              ) : null}
            </div>
            <div className="grid grid-cols-1 gap-2.5">
              {rows.map((category) => (
                <CategoryRow
                  key={category.id}
                  category={category}
                  siteNames={siteNamesOf(category)}
                  isNew={category.id === justCreatedId}
                  edge={edgeIds.has(category.id)}
                  onEditSites={openSites}
                  onAdded={onAdded}
                />
              ))}
            </div>
          </section>
        ) : null}
        {dialogs}
      </div>
    )
  }

  const shownRows = showAllRows ? rows : rows.slice(0, ROWS_SHOWN)
  const hiddenRows = rows.length - shownRows.length
  return (
    <div>
      <VerdictHero items={myItems} drops={dropsByItem} className={cn(items.isFetching && 'opacity-60')} />
      <HunterTicker className="mt-2" />

      <section className="mt-[26px]">
        <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3.5 gap-y-2">
          <h2 className="font-display text-[19px] font-semibold tracking-[0.12em] text-ink-2 uppercase">The Watch</h2>
          <span className="font-mono text-[11px] text-ink-3 tnum">
            {shelves.length} {shelves.length === 1 ? 'shelf' : 'shelves'} · {myItems.length}{' '}
            {myItems.length === 1 ? 'item' : 'items'}
          </span>
          <span className="flex-1" />
          {shelves.length >= 2 ? (
            <Button variant="ghost" size="sm" onClick={toggleAll}>
              {anyOpen ? 'Collapse all' : 'Expand all'}
            </Button>
          ) : null}
          <RangeSelector value={range} onChange={setRange} className="max-sm:order-last max-sm:w-full" />
          <CreateCategoryDialog trigger="＋ New category" onCreated={onCreated} />
        </div>

        <LabelStrip hidden={!anyOpen} />
        <div className={cn('grid grid-cols-1 gap-2.5', items.isFetching && 'opacity-60')}>
          {shelves.map((shelf, i) => (
            <CategoryShelf
              key={shelf.category.id}
              shelf={shelf}
              siteNames={siteNamesOf(shelf.category)}
              open={resolved[i].open}
              onToggle={(open) => toggle(i, open)}
              drops={dropsByItem}
              struck={struckIds}
              edge={edgeIds.has(shelf.category.id)}
              openDelay={cascading ? Math.min(i, CASCADE_MAX_STEPS) * CASCADE_STEP_MS : 0}
              onEditSites={openSites}
              onRename={openRename}
            />
          ))}
        </div>

        {rows.length > 0 ? (
          <>
            <h3 className="mt-[18px] mb-1 ml-0.5 font-mono text-[10px] font-medium tracking-[0.14em] text-ink-3 uppercase">
              No items of yours yet
            </h3>
            <div className="grid grid-cols-1 gap-2.5">
              {shownRows.map((category) => (
                <CategoryRow
                  key={category.id}
                  category={category}
                  siteNames={siteNamesOf(category)}
                  isNew={category.id === justCreatedId}
                  edge={edgeIds.has(category.id)}
                  onEditSites={openSites}
                  onAdded={onAdded}
                />
              ))}
            </div>
            {hiddenRows > 0 ? (
              <Button variant="ghost" size="sm" className="mt-2" onClick={() => setShowAllRows(true)}>
                ＋ {hiddenRows} more {hiddenRows === 1 ? 'category' : 'categories'}
              </Button>
            ) : null}
          </>
        ) : null}
      </section>
      {dialogs}
    </div>
  )
}

/** The column labels, once, above every shelf; hidden while no shelf is open to label. */
function LabelStrip({ hidden }: { hidden?: boolean }) {
  // transparent side borders match the shelves' own, so the columns line up to the pixel
  return (
    <div hidden={hidden} className="sticky top-0 z-10 mb-2.5 border-x border-transparent bg-page">
      <WatchListLabels showSite />
    </div>
  )
}

/** `?search=`: only the shelves holding a match, all open, with no hero, rows or collapse state. */
function SearchResults({
  search,
  matches,
  myItems,
  categories,
  loading,
  error,
  siteNamesOf,
  drops,
  onEditSites,
  onRename,
}: {
  search: string
  matches: ItemSummary[] | undefined
  myItems: ItemSummary[]
  categories: Category[]
  loading: boolean
  error: ReactNode
  siteNamesOf: (category: Category) => string[]
  drops: Map<number, PriceDrop>
  onEditSites: (category: Category) => void
  onRename: (category: Category) => void
}) {
  const { shelves } = useMemo(() => groupShelves(matches ?? [], categories), [matches, categories])
  const totals = useMemo(() => {
    const map = new Map<number, number>()
    for (const item of myItems) map.set(item.category_id, (map.get(item.category_id) ?? 0) + 1)
    return map
  }, [myItems])
  const clear = (
    <Link to="/" className="text-ink-2 hover:text-lume">
      clear
    </Link>
  )

  return (
    <section>
      <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3.5 gap-y-2">
        <h2 className="font-display text-[19px] font-semibold tracking-[0.12em] text-ink-2 uppercase">Search</h2>
        <span className="font-mono text-[11px] text-ink-3">
          matching “{search}” · {clear}
        </span>
      </div>
      {loading ? (
        <div className="space-y-2.5">
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : error ? (
        error
      ) : shelves.length === 0 ? (
        <p className="rounded-md border border-dashed border-hairline-strong px-3.5 py-[26px] text-center text-[13px] text-ink-3">
          Nothing on any shelf matches “{search}”. · {clear}
        </p>
      ) : (
        <>
          <LabelStrip />
          <div className="grid grid-cols-1 gap-2.5">
            {shelves.map((shelf) => (
              <CategoryShelf
                key={shelf.category.id}
                shelf={shelf}
                siteNames={siteNamesOf(shelf.category)}
                open
                total={totals.get(shelf.category.id) ?? shelf.items.length}
                drops={drops}
                onEditSites={onEditSites}
                onRename={onRename}
              />
            ))}
          </div>
        </>
      )}
    </section>
  )
}
