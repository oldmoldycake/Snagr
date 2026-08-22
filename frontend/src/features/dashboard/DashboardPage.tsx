import { useMemo } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Plus } from 'lucide-react'
import { getDashboardStats, getPriceDrops, listCategories, listItems } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { PriceDrop } from '@/api/types'
import { RangeSelector, useRangeParam } from '@/components/charts/RangeSelector'
import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { AddItemDialog } from '@/features/items/AddItemDialog'
import { sortByDistanceToTarget, WatchList } from '@/features/items/WatchList'
import { CategoryChips } from '@/features/categories/CategoryChips'
import { CreateCategoryDialog } from '@/features/categories/CreateCategoryDialog'
import { AgentTicker } from '@/features/runs/AgentTicker'
import { VerdictHero } from './VerdictHero'

/** One page of everything: the self-hosted watch fits in a single fetch. */
const WATCH_PAGE_SIZE = 200

export function DashboardPage() {
  const [range, setRange] = useRangeParam()
  const [params] = useSearchParams()
  const search = params.get('search') ?? undefined

  const stats = useQuery({
    queryKey: qk.dashboard(range),
    queryFn: () => getDashboardStats(range),
    placeholderData: keepPreviousData,
  })
  const drops = useQuery({
    queryKey: qk.dashboardDrops(range),
    queryFn: () => getPriceDrops(range, 20),
    placeholderData: keepPreviousData,
  })
  const items = useQuery({
    queryKey: qk.items({ range, search, per_page: WATCH_PAGE_SIZE }),
    queryFn: () => listItems({ range, search, per_page: WATCH_PAGE_SIZE }),
    placeholderData: keepPreviousData,
  })
  const categories = useQuery({ queryKey: qk.categories, queryFn: listCategories })

  const rows = useMemo(() => sortByDistanceToTarget(items.data?.data ?? []), [items.data])
  const dropsByItem = useMemo(() => {
    const map = new Map<number, PriceDrop>()
    for (const drop of drops.data?.data ?? []) {
      if (!map.has(drop.item_id)) map.set(drop.item_id, drop) // newest first
    }
    return map
  }, [drops.data])

  // Bootstrap only when there is truly nothing — with categories but no items,
  // the page must still render (the chips line is the only category nav).
  const isBootstrap =
    items.isSuccess &&
    categories.isSuccess &&
    rows.length === 0 &&
    categories.data.data.length === 0 &&
    !search

  if (isBootstrap) {
    return (
      <EmptyState
        title="Set your first target"
        description="Create a category, link the sites to search, and add an item with a target price. The agent does the rest."
        action={
          <CreateCategoryDialog
            trigger={
              <span className="inline-flex items-center gap-1.5">
                <Plus className="size-4" /> New category
              </span>
            }
          />
        }
      />
    )
  }

  return (
    <div>
      {search || (items.isSuccess && rows.length === 0) ? null : items.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-11 w-72" />
          <Skeleton className="h-5 w-96" />
        </div>
      ) : (
        <VerdictHero items={rows} className={cn(items.isFetching && 'opacity-60')} />
      )}

      {search ? null : <AgentTicker className="mt-9" />}

      <section className={search ? undefined : 'mt-7'}>
        <div className="mb-3 flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <h2 className="font-display text-[19px] font-semibold tracking-[0.12em] text-ink-2 uppercase">
            {search ? 'Search' : 'The Watch'}
          </h2>
          {search ? (
            <span className="font-mono text-[11px] text-ink-3">
              matching “{search}” ·{' '}
              <Link to="/" className="text-ink-2 hover:text-lume">
                clear
              </Link>
            </span>
          ) : stats.data ? (
            <span className="font-mono text-[11px] text-ink-3 tnum">
              {stats.data.tracked_items.value} items · {stats.data.active_listings.value} listings
            </span>
          ) : null}
          {search ? null : <CategoryChips className="ml-2" />}
          <span className="flex-1" />
          <RangeSelector value={range} onChange={setRange} />
          <AddItemDialog />
        </div>

        <Card className={cn(items.isFetching && 'opacity-60')}>
          {items.isLoading ? (
            <div className="space-y-2 p-4">
              <Skeleton className="h-6" />
              <Skeleton className="h-6" />
              <Skeleton className="h-6" />
            </div>
          ) : rows.length === 0 && search ? (
            <p className="px-4 py-6 text-[13px] text-ink-3">No items match this search.</p>
          ) : rows.length === 0 ? (
            <EmptyState
              className="m-4 border-0"
              title="Add an item to start tracking"
              description="Pick a category, give the item a name and a target price — the agent searches the category's sites for listings."
              action={<AddItemDialog />}
            />
          ) : (
            <>
              <WatchList items={rows} drops={dropsByItem} showCategory />
              <div className="flex items-center justify-between border-t border-hairline bg-well px-4 py-2 font-mono text-[11px] text-ink-3">
                <span>
                  {rows.length} {rows.length === 1 ? 'item' : 'items'} · sorted by distance to target
                </span>
              </div>
            </>
          )}
        </Card>
      </section>
    </div>
  )
}
