import { useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ChevronDown, ChevronRight, ExternalLink, Pencil, Trash2 } from 'lucide-react'
import {
  deleteItem,
  getItem,
  getPriceHistory,
  getPriceSummary,
  listPriceChecks,
  listSites,
  updateListing,
  updateWatch,
} from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ItemDetail, Listing } from '@/api/types'
import { RangeSelector, useRangeParam } from '@/components/charts/RangeSelector'
import { Badge, SnaggedBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/table'
import { SimpleTooltip } from '@/components/ui/tooltip'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/money'
import { formatDateTime, relativeTime } from '@/lib/time'
import { RunButton } from '@/features/runs/RunButton'
import { EditItemDialog } from './EditItemDialog'
import { AvgBestChart } from './AvgBestChart'
import { MatchPill } from './MatchPill'
import { PriceHistoryChart } from './PriceHistoryChart'

function ListingRow({
  listing,
  itemId,
  isBestMatch,
}: {
  listing: Listing
  itemId: number
  isBestMatch: boolean
}) {
  const queryClient = useQueryClient()
  const toggle = useMutation({
    mutationFn: (active: boolean) => updateListing(listing.id, { active }),
    // optimistic: flip immediately, roll back on error
    onMutate: async (active) => {
      await queryClient.cancelQueries({ queryKey: qk.item(itemId) })
      const prev = queryClient.getQueryData<ItemDetail>(qk.item(itemId))
      if (prev) {
        queryClient.setQueryData<ItemDetail>(qk.item(itemId), {
          ...prev,
          listings: prev.listings.map((l) => (l.id === listing.id ? { ...l, active } : l)),
        })
      }
      return { prev }
    },
    onError: (_err, _active, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(qk.item(itemId), ctx.prev)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
    },
  })

  const soldOrEnded =
    !listing.active && (listing.latest_status === 'sold' || listing.latest_status === 'ended')

  return (
    <TR className={cn(!listing.active && 'opacity-45')}>
      <TD>
        <div className="flex items-center gap-2">
          <div className="min-w-0">
            <a
              href={listing.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex max-w-72 items-center gap-1 text-[13px] text-ink hover:text-accent hover:underline"
            >
              <span className="truncate">
                {listing.title ?? listing.url.replace(/^https?:\/\/(www\.)?/, '')}
              </span>
              <ExternalLink className="size-3 shrink-0 text-ink-3" />
            </a>
            <p className="text-xs text-ink-3">{listing.site_name}</p>
          </div>
          {isBestMatch ? (
            <Badge variant="accent" className="shrink-0">
              Best match
            </Badge>
          ) : null}
        </div>
      </TD>
      <TD>
        <MatchPill score={listing.match_score} summary={listing.match_summary} />
      </TD>
      <TD className="text-right font-mono text-ink tnum">{formatMoney(listing.latest_price)}</TD>
      <TD>
        {soldOrEnded ? (
          <Badge variant="warn">
            {listing.latest_status === 'sold' ? 'Sold' : 'Ended'} · {relativeTime(listing.last_checked_at)}
          </Badge>
        ) : listing.in_stock == null ? (
          <span className="text-xs text-ink-3">—</span>
        ) : (
          <span className="flex items-center gap-1.5 text-xs text-ink-2">
            <span
              aria-hidden
              className={cn('size-1.5 rounded-full', listing.in_stock ? 'bg-drop' : 'bg-rise')}
            />
            {listing.in_stock ? 'In stock' : 'Out of stock'}
          </span>
        )}
      </TD>
      <TD className="text-xs whitespace-nowrap text-ink-3">{relativeTime(listing.last_checked_at)}</TD>
      <TD className="text-xs whitespace-nowrap text-ink-3">
        {listing.discovered_by_run_id != null ? (
          <Link to={`/runs/${listing.discovered_by_run_id}`} className="hover:text-ink hover:underline">
            {relativeTime(listing.created_at)}
          </Link>
        ) : (
          relativeTime(listing.created_at)
        )}
      </TD>
      <TD>
        <SimpleTooltip content={listing.active ? 'Active — the agent checks this listing' : 'Inactive — skipped by the agent'}>
          <span>
            <Switch
              checked={listing.active}
              onCheckedChange={(active) => toggle.mutate(active)}
              aria-label={`${listing.active ? 'Deactivate' : 'Activate'} ${listing.site_name} listing`}
            />
          </span>
        </SimpleTooltip>
      </TD>
    </TR>
  )
}

export function ItemDetailPage() {
  const { id = '' } = useParams()
  const itemId = Number(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [range, setRange] = useRangeParam()
  const [editOpen, setEditOpen] = useState(false)
  const [logOpen, setLogOpen] = useState(false)

  const item = useQuery({ queryKey: qk.item(itemId), queryFn: () => getItem(itemId) })
  const history = useQuery({
    queryKey: qk.itemHistory(itemId, range),
    queryFn: () => getPriceHistory(itemId, range),
    placeholderData: keepPreviousData,
  })
  const summary = useQuery({
    queryKey: qk.itemSummary(itemId, range),
    queryFn: () => getPriceSummary(itemId, range),
    placeholderData: keepPreviousData,
  })
  const checks = useQuery({
    queryKey: qk.itemChecks(itemId),
    queryFn: () => listPriceChecks(itemId, 50),
    enabled: logOpen,
  })
  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })

  const notifyToggle = useMutation({
    mutationFn: (notify: boolean) => updateWatch(itemId, { notify }),
    onMutate: async (notify) => {
      await queryClient.cancelQueries({ queryKey: qk.item(itemId) })
      const prev = queryClient.getQueryData<ItemDetail>(qk.item(itemId))
      if (prev) {
        queryClient.setQueryData<ItemDetail>(qk.item(itemId), {
          ...prev,
          watch: { ...prev.watch, notify },
        })
      }
      return { prev }
    },
    onError: (_e, _v, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(qk.item(itemId), ctx.prev)
    },
    onSettled: () => void queryClient.invalidateQueries({ queryKey: ['items'] }),
  })

  const remove = useMutation({
    mutationFn: () => deleteItem(itemId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      navigate(`/categories/${item.data?.category_slug ?? ''}`)
    },
  })

  if (item.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-72" />
        <Skeleton className="h-64" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  if (!item.data) {
    return <EmptyState title="Item not found" description="It may have been deleted." />
  }

  const detail = item.data
  const target = detail.watch.target_price ?? detail.target_price

  // badge the highest-scoring tracked listing (price breaks ties) in best_match mode
  const bestMatchListingId =
    detail.selection_mode === 'best_match'
      ? [...detail.listings]
          .filter((l) => l.active && l.match_score != null)
          .sort(
            (a, b) =>
              (b.match_score ?? 0) - (a.match_score ?? 0) ||
              Number(a.latest_price ?? Infinity) - Number(b.latest_price ?? Infinity),
          )[0]?.id ?? null
      : null

  const trackedCount = detail.listings.filter((l) => l.active).length

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs text-ink-3">
            <Link to={`/categories/${detail.category_slug}`} className="hover:text-ink-2 hover:underline">
              {detail.category_name}
            </Link>{' '}
            /
          </p>
          <div className="mt-0.5 flex flex-wrap items-center gap-2">
            <h1 className="font-display text-lg font-semibold text-ink">{detail.name}</h1>
            {detail.target_met ? <SnaggedBadge /> : null}
            <Button variant="ghost" size="iconSm" aria-label="Edit item" onClick={() => setEditOpen(true)}>
              <Pencil />
            </Button>
            <Button
              variant="ghost"
              size="iconSm"
              aria-label="Delete item"
              className="text-rise"
              onClick={() => {
                if (window.confirm(`Delete “${detail.name}” and its price history?`)) remove.mutate()
              }}
            >
              <Trash2 />
            </Button>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
            <span className="font-mono text-sm tnum">
              <span className={cn(detail.target_met ? 'text-drop' : 'text-ink')}>
                {formatMoney(detail.best_price, detail.currency)}
              </span>
              <span className="text-ink-3"> best · {formatMoney(detail.avg_price, detail.currency)} avg</span>
            </span>
            <span className="font-mono text-sm text-ink-3 tnum">
              target {formatMoney(target, detail.currency)}
            </span>
            <label className="flex items-center gap-1.5 text-xs text-ink-2">
              <Switch
                checked={detail.watch.notify}
                onCheckedChange={(v) => notifyToggle.mutate(v)}
                aria-label="Notify me when the target price is hit"
              />
              Notify at target
            </label>
          </div>
          {detail.criteria ? (
            <p className="mt-1.5 max-w-xl text-xs text-ink-2 italic">“{detail.criteria}”</p>
          ) : null}
          <div className="mt-1.5">
            <Badge variant="muted">
              {detail.selection_mode === 'best_match' ? 'Best match' : 'Cheapest'} · {trackedCount}/
              {detail.max_listings} slots
              {' · '}
              {detail.site_ids == null
                ? 'all category sites'
                : (sites.data?.data ?? [])
                    .filter((s) => detail.site_ids!.includes(s.id))
                    .map((s) => s.name)
                    .join(', ') || `${detail.site_ids.length} sites`}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <RangeSelector value={range} onChange={setRange} />
          <RunButton scope="item" scopeId={detail.id} label="Run agent on this item" variant="snag" size="sm" />
        </div>
      </div>

      <Card className={cn(history.isFetching && 'opacity-60')}>
        <CardHeader>
          <CardTitle>Listing price history</CardTitle>
        </CardHeader>
        <CardBody className="px-2">
          {history.isLoading ? (
            <Skeleton className="m-2 h-56" />
          ) : history.data ? (
            <PriceHistoryChart data={history.data} range={range} />
          ) : null}
        </CardBody>
      </Card>

      <Card className={cn(summary.isFetching && 'opacity-60')}>
        <CardHeader>
          <CardTitle>Average vs best price</CardTitle>
        </CardHeader>
        <CardBody className="px-2">
          {summary.isLoading ? (
            <Skeleton className="m-2 h-48" />
          ) : summary.data ? (
            <AvgBestChart data={summary.data} range={range} />
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Listings</CardTitle>
        </CardHeader>
        <CardBody className="px-0 pb-1">
          {detail.listings.length === 0 ? (
            <EmptyState
              className="m-4 border-0"
              title={detail.criteria ? 'No listings met your criteria' : 'No listings yet'}
              description={
                detail.criteria
                  ? 'The agent left the slots empty rather than track poor matches. Loosen the criteria, or run it again to search for new candidates.'
                  : "The agent finds listings by searching this category's sites — run it on this item to discover them."
              }
              action={<RunButton scope="item" scopeId={detail.id} label="Run agent on this item" variant="snag" size="sm" />}
            />
          ) : (
            <Table>
              <THead>
                <TR>
                  <TH>Listing</TH>
                  <TH>Match</TH>
                  <TH className="text-right">Latest price</TH>
                  <TH>Stock</TH>
                  <TH>Checked</TH>
                  <TH>Discovered</TH>
                  <TH>Active</TH>
                </TR>
              </THead>
              <TBody>
                {detail.listings.map((listing) => (
                  <ListingRow
                    key={listing.id}
                    listing={listing}
                    itemId={detail.id}
                    isBestMatch={bestMatchListingId === listing.id}
                  />
                ))}
              </TBody>
            </Table>
          )}
        </CardBody>
      </Card>

      <Collapsible open={logOpen} onOpenChange={setLogOpen}>
        <CollapsibleTrigger className="flex items-center gap-1 text-xs text-ink-3 hover:text-ink-2">
          {logOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
          Recent price checks
        </CollapsibleTrigger>
        <CollapsibleContent>
          <Card className="mt-2">
            <CardBody className="px-0 py-1">
              {checks.isLoading ? (
                <div className="space-y-2 p-4">
                  <Skeleton className="h-5" />
                  <Skeleton className="h-5" />
                </div>
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>Time</TH>
                      <TH>Site</TH>
                      <TH className="text-right">Price</TH>
                      <TH>Status</TH>
                      <TH>Stock</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {(checks.data?.data ?? []).map((check) => (
                      <TR key={check.id}>
                        <TD className="font-mono text-xs whitespace-nowrap text-ink-3 tnum">
                          {formatDateTime(check.checked_at)}
                        </TD>
                        <TD className="text-ink-2">{check.site_name}</TD>
                        <TD className="text-right font-mono tnum">{formatMoney(check.price, check.currency)}</TD>
                        <TD className="font-mono text-xs text-ink-3">{check.status ?? '—'}</TD>
                        <TD className="text-xs text-ink-3">
                          {check.in_stock == null ? '—' : check.in_stock ? 'in stock' : 'out of stock'}
                        </TD>
                      </TR>
                    ))}
                  </TBody>
                </Table>
              )}
            </CardBody>
          </Card>
        </CollapsibleContent>
      </Collapsible>

      <EditItemDialog
        key={`${detail.id}-${detail.name}-${detail.target_price}-${detail.criteria}-${detail.selection_mode}-${detail.max_listings}-${(detail.site_ids ?? []).join(',')}`}
        item={detail}
        open={editOpen}
        onOpenChange={setEditOpen}
      />
    </div>
  )
}
