import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ExternalLink, Plus } from 'lucide-react'
import { getDashboardStats, getPriceDrops, listItems } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { RangeSelector, useRangeParam } from '@/components/charts/RangeSelector'
import { DeltaText } from '@/components/charts/DeltaText'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/money'
import { relativeTime } from '@/lib/time'
import { ItemsTable } from '@/features/items/ItemsTable'
import { CreateCategoryDialog } from '@/features/categories/CreateCategoryDialog'
import { StatTile } from './StatTile'

export function DashboardPage() {
  const [range, setRange] = useRangeParam()
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const search = params.get('search') ?? undefined

  const stats = useQuery({
    queryKey: qk.dashboard(range),
    queryFn: () => getDashboardStats(range),
    placeholderData: keepPreviousData,
  })
  const drops = useQuery({
    queryKey: qk.dashboardDrops(range),
    queryFn: () => getPriceDrops(range, 8),
    placeholderData: keepPreviousData,
  })
  const items = useQuery({
    queryKey: qk.items({ range, search }),
    queryFn: () => listItems({ range, search }),
    placeholderData: keepPreviousData,
  })

  const rows = items.data?.data ?? []
  const snagged = rows.filter((r) => r.target_met)
  const isEmpty = items.isSuccess && rows.length === 0 && !search

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-display text-lg font-semibold text-ink">Dashboard</h1>
        <RangeSelector value={range} onChange={setRange} />
      </div>

      {isEmpty ? (
        <EmptyState
          title="Track your first item"
          description="Create a category, link the sites to search, and add an item with a target price. The agent does the rest."
          action={<CreateCategoryDialog trigger={<span className="inline-flex items-center gap-1.5"><Plus className="size-4" /> New category</span>} />}
        />
      ) : (
        <>
          <div className={cn('grid grid-cols-2 gap-3 lg:grid-cols-4', stats.isFetching && 'opacity-60')}>
            <StatTile label="Tracked items" data={stats.data?.tracked_items} />
            <StatTile label="Active listings" data={stats.data?.active_listings} />
            <StatTile label="Price drops" data={stats.data?.price_drops} polarity="neutral" />
            <StatTile label="Snagged" data={stats.data?.snagged} />
          </div>

          {snagged.length > 0 ? (
            <Card className="border-drop/30">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <span aria-hidden className="text-drop">⌖</span> Snagged — at or below target
                </CardTitle>
              </CardHeader>
              <CardBody className="flex flex-wrap gap-3">
                {snagged.map((item) => (
                  <Link
                    key={item.id}
                    to={`/items/${item.id}`}
                    className="flex min-w-52 flex-col gap-0.5 rounded-md border border-drop/30 bg-drop/5 px-3 py-2 hover:bg-drop/10"
                  >
                    <span className="text-[13px] font-medium text-ink">{item.name}</span>
                    <span className="font-mono text-xs tnum">
                      <span className="text-drop">{formatMoney(item.best_price, item.currency)}</span>
                      <span className="text-ink-3">
                        {' '}
                        vs {formatMoney(item.watch.target_price ?? item.target_price, item.currency)} target ·{' '}
                        {item.best_site_name}
                      </span>
                    </span>
                  </Link>
                ))}
              </CardBody>
            </Card>
          ) : null}

          <Card className={cn(drops.isFetching && 'opacity-60')}>
            <CardHeader>
              <CardTitle>Recent price drops</CardTitle>
            </CardHeader>
            <CardBody className="px-0 pb-1">
              {drops.isLoading ? (
                <div className="space-y-2 px-4 pb-3">
                  <Skeleton className="h-6" />
                  <Skeleton className="h-6" />
                </div>
              ) : (drops.data?.data.length ?? 0) === 0 ? (
                <p className="px-4 pb-4 text-[13px] text-ink-3">
                  No price drops in this range. Run the agent to check for fresh prices.
                </p>
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>Item</TH>
                      <TH>Site</TH>
                      <TH className="text-right">Price</TH>
                      <TH className="text-right">Change</TH>
                      <TH>When</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {drops.data!.data.map((drop) => (
                      <TR
                        key={`${drop.listing_id}-${drop.checked_at}`}
                        data-clickable="true"
                        onClick={() => navigate(`/items/${drop.item_id}`)}
                      >
                        <TD className="font-medium text-ink">{drop.item_name}</TD>
                        <TD className="text-ink-2">
                          <span className="inline-flex items-center gap-1">
                            {drop.site_name} <ExternalLink className="size-3 text-ink-3" />
                          </span>
                        </TD>
                        <TD className="text-right font-mono tnum">
                          <span className="text-ink-3 line-through">{formatMoney(drop.old_price, drop.currency)}</span>{' '}
                          <span className="text-ink">{formatMoney(drop.new_price, drop.currency)}</span>
                        </TD>
                        <TD className="text-right">
                          <DeltaText value={drop.pct_change} />
                        </TD>
                        <TD className="text-xs whitespace-nowrap text-ink-3">{relativeTime(drop.checked_at)}</TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardBody>
          </Card>

          <Card className={cn(items.isFetching && 'opacity-60')}>
            <CardHeader>
              <CardTitle>{search ? `Items matching “${search}”` : 'All tracked items'}</CardTitle>
            </CardHeader>
            <CardBody className="px-0 pb-1">
              {items.isLoading ? (
                <div className="space-y-2 px-4 pb-3">
                  <Skeleton className="h-6" />
                  <Skeleton className="h-6" />
                  <Skeleton className="h-6" />
                </div>
              ) : rows.length === 0 ? (
                <p className="px-4 pb-4 text-[13px] text-ink-3">No items match this search.</p>
              ) : (
                <ItemsTable items={rows} showCategory showLastChecked />
              )}
            </CardBody>
          </Card>
        </>
      )}
    </div>
  )
}
