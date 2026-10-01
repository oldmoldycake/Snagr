import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ApiError, isNotFound } from '@/api/client'
import { deleteItem, getItem, listPriceChecks, listSites, updateWatch } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ItemDetail, PriceCheck } from '@/api/types'
import { useRangeParam } from '@/components/charts/RangeSelector'
import { SnaggedBadge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Glossary } from '@/components/ui/glossary'
import { TERMS } from '@/components/ui/glossaryTerms'
import { NotFound } from '@/components/ui/not-found'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { TerminalLog, type LogLine } from '@/components/ui/terminal-log'
import { RelativeTime } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/money'
import { priceMethodLabel } from '@/lib/priceMethod'
import { formatDateTime } from '@/lib/time'
import { usePageTitle } from '@/lib/usePageTitle'
import { useInstance } from '@/features/auth/useSession'
import { CheckPricesButton } from '@/features/activity/CheckPricesButton'
import { HuntButton } from '@/features/activity/HuntButton'
import { HunterLine } from '@/features/activity/HunterLine'
import { ReferenceLibrary } from '@/features/vision/ReferenceLibrary'
import { ChartPanel } from './ChartPanel'
import { EditItemDialog } from './EditItemDialog'
import { Ladder } from './Ladder'
import { ListingsBoard } from './ListingsBoard'

/**
 * Only the exceptions are marked. A price the model read looks exactly as it
 * always has; a price code read off the listing's stored locator carries a dim
 * tag saying where from, and a reading the plausibility bands rejected dims
 * the whole row and says so — it is shown, but it counts for nothing until a
 * later reading agrees with it.
 */
function checkLine(check: PriceCheck): LogLine {
  const level =
    check.status === 'ok'
      ? 'success'
      : check.status === 'error'
        ? 'warn'
        : check.status === 'sold' || check.status === 'ended'
          ? 'error'
          : 'info'
  const text =
    check.status === 'sold' || check.status === 'ended'
      ? `${check.status} · ${check.site_name}`
      : check.status === 'error'
        ? `check failed · ${check.site_name}`
        : `${formatMoney(check.price, check.currency)} · ${
            check.in_stock == null ? 'stock unknown' : check.in_stock ? 'in stock' : 'out of stock'
          } · ${check.site_name}`
  const marks = [
    priceMethodLabel(check.method),
    check.confirmed ? null : 'unconfirmed',
  ].filter(Boolean)
  const message = (
    <span className={cn(check.confirmed ? undefined : 'text-ink-3')}>
      {text}
      {marks.length > 0 ? (
        <span className="ml-2 text-ink-3">{marks.join(' · ')}</span>
      ) : null}
    </span>
  )
  return { key: check.id, time: formatDateTime(check.checked_at), level, message }
}

const CHECKS_PREVIEW = 8

/** The words on this page that stay because no plainer one says the same. */
const ITEM_TERMS = [
  TERMS.target,
  TERMS.vsTarget,
  TERMS.change,
  TERMS.match,
  TERMS.mode,
  TERMS.tracked,
  TERMS.hunt,
  TERMS.pageData,
  TERMS.learnedSpot,
  TERMS.unconfirmed,
  TERMS.replicas,
]

/**
 * One item's page at /items/:id: price charts, the listings board, recent
 * price checks and, when vision is on, its reference library.
 */
export function ItemDetailPage() {
  const { id = '' } = useParams()
  const itemId = Number(id)
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [range, setRange] = useRangeParam()
  const [editOpen, setEditOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [allChecks, setAllChecks] = useState(false)

  const { data: instance } = useInstance()
  const item = useQuery({ queryKey: qk.item(itemId), queryFn: () => getItem(itemId) })
  const checks = useQuery({
    queryKey: qk.itemChecks(itemId),
    queryFn: () => listPriceChecks(itemId, 50),
  })
  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })
  usePageTitle(item.data?.name ?? (isNotFound(item.error) ? 'Item not found' : undefined))

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
    meta: { inlineError: true },
    onSuccess: () => {
      // removed, not invalidated: Back would otherwise paint the cached page, live buttons and all
      queryClient.removeQueries({ queryKey: qk.item(itemId) })
      void queryClient.invalidateQueries({ queryKey: ['items'] })
      void queryClient.invalidateQueries({ queryKey: ['categories'] })
      void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
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

  if (item.isError && !isNotFound(item.error)) {
    return (
      <ErrorState
        title="Couldn't load this item"
        error={item.error}
        onRetry={() => void item.refetch()}
        retrying={item.isFetching}
      />
    )
  }

  if (!item.data) {
    return <NotFound title="Item not found" description="It may have been deleted." />
  }

  const detail = item.data
  const target = detail.watch.target_price ?? detail.target_price
  const bestListing = detail.listings.find((l) => l.id === detail.best_listing_id) ?? null

  const trackedCount = detail.listings.filter((l) => l.active).length
  const siteNames =
    detail.site_ids == null
      ? 'all category sites'
      : (sites.data?.data ?? [])
          .filter((s) => detail.site_ids!.includes(s.id))
          .map((s) => s.name)
          .join(', ') || `${detail.site_ids.length} sites`

  const checkRows = checks.data?.data ?? []
  const shownChecks = allChecks ? checkRows : checkRows.slice(0, CHECKS_PREVIEW)

  return (
    <div>
      <div className="flex items-center gap-3">
        <p className="min-w-0 flex-1 font-mono text-[12px] tracking-[0.06em] wrap-anywhere text-ink-3 uppercase">
          <Link to={`/categories/${detail.category_slug}`} className="hover:text-lume">
            {detail.category_name}
          </Link>{' '}
          / {detail.name}
        </p>
        <Glossary terms={ITEM_TERMS} className="-my-1 shrink-0" />
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-3">
        <h1 className="min-w-0 font-display text-[30px] leading-tight font-semibold tracking-[0.02em] wrap-anywhere text-ink">
          {detail.name}
        </h1>
        {detail.target_met ? <SnaggedBadge /> : null}
        <span className="flex-1" />
        {/* a full watch is never hunted on its own; asking is a swap hunt,
            which trades its weakest listing for something better (HunterLine says so) */}
        <HuntButton
          scope="item"
          scopeId={detail.id}
          label={detail.hunt.slots_open === 0 ? 'Hunt for better' : 'Hunt now'}
          size="sm"
        />
        <CheckPricesButton scope="item" scopeId={detail.id} size="sm" />
        <Button size="sm" onClick={() => setEditOpen(true)}>
          Edit
        </Button>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-x-7 gap-y-4">
        <div
          className={cn(
            'font-display text-[52px] leading-none font-bold tnum',
            detail.target_met ? 'text-drop' : 'text-ink',
            detail.best_price == null && 'text-ink-3',
          )}
        >
          {formatMoney(detail.best_price, detail.currency)}
        </div>
        <div className="pb-1">
          <p className="font-mono text-[14px] text-ink-2 tnum">
            target <span className="font-semibold text-ink">{formatMoney(target, detail.currency)}</span>
            {' · '}best of {trackedCount} tracked {trackedCount === 1 ? 'listing' : 'listings'}
          </p>
          <p className="mt-1 font-mono text-[12px] text-ink-3">
            avg {formatMoney(detail.avg_price, detail.currency)}
            {detail.best_site_name ? ` · ${detail.best_site_name}` : ''}
            {' · checked '}
            <RelativeTime iso={detail.last_checked_at} />
            {bestListing ? (
              <>
                {' · '}
                <a
                  href={bestListing.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-ink-2 hover:text-lume"
                >
                  open listing ↗
                </a>
              </>
            ) : null}
          </p>
          <HunterLine detail={detail} />
        </div>
        <Ladder
          spark={detail.spark}
          best={detail.best_price}
          target={target}
          currency={detail.currency}
          range={range}
          className="mb-1 ml-auto"
        />
      </div>

      <div className="mt-7 grid gap-6 lg:grid-cols-[minmax(0,1fr)_280px]">
        <div className="min-w-0 space-y-6">
          <ChartPanel itemId={itemId} range={range} onRangeChange={setRange} />

          <Card>
            <CardHeader>
              <CardTitle>Listings</CardTitle>
              <span className="font-mono text-[12px] text-ink-3 tnum">
                {trackedCount} tracked
                {detail.listings.length > trackedCount ? ` · ${detail.listings.length - trackedCount} not tracked` : ''}
                {detail.selection_mode === 'best_match' ? ' · picked by best match' : ''}
              </span>
            </CardHeader>
            <CardBody className="px-0 pb-1">
              {detail.listings.length === 0 ? (
                <EmptyState
                  className="m-4 border-0"
                  title={detail.criteria ? 'No listings met your criteria' : 'No listings yet'}
                  description={
                    detail.criteria
                      ? 'Snagr found listings, but none matched your criteria well enough to track. Loosen the criteria, or press Hunt now to try again.'
                      : "Snagr finds listings by searching this category's sites. It's already looking, and Hunt now asks it to look again."
                  }
                  action={<HuntButton scope="item" scopeId={detail.id} variant="snag" size="sm" />}
                />
              ) : (
                <ListingsBoard detail={detail} range={range} />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Recent checks</CardTitle>
              <div className="flex items-center gap-3">
                <span className="font-mono text-[12px] text-ink-3 tnum">
                  {shownChecks.length} of {checkRows.length}
                </span>
                {checkRows.length > CHECKS_PREVIEW ? (
                  <Button variant="ghost" size="sm" onClick={() => setAllChecks((v) => !v)}>
                    {allChecks ? 'Show fewer' : 'Show all'}
                  </Button>
                ) : null}
              </div>
            </CardHeader>
            <div className="border-t border-hairline bg-well px-4 py-3">
              {checks.isLoading ? (
                <div className="space-y-2">
                  <Skeleton className="h-5" />
                  <Skeleton className="h-5" />
                </div>
              ) : checks.isError ? (
                <ErrorState
                  className="border-0 py-4"
                  title="Couldn't load the checks"
                  error={checks.error}
                  onRetry={() => void checks.refetch()}
                  retrying={checks.isFetching}
                />
              ) : checkRows.length === 0 ? (
                <p className="py-2 font-mono text-[12px] text-ink-3">
                  No price checks yet. They appear once Snagr is tracking a listing.
                </p>
              ) : (
                <TerminalLog lines={shownChecks.map(checkLine)} />
              )}
            </div>
          </Card>

          {instance?.vision_enabled ? <ReferenceLibrary itemId={itemId} /> : null}
        </div>

        <div>
          <Card className="p-4">
            <CardTitle className="mb-2">Tracking</CardTitle>
            <dl>
              {[
                ['Target', formatMoney(target, detail.currency)],
                ['Mode', detail.selection_mode === 'best_match' ? 'Best match' : 'Cheapest'],
                ['Listings', `${trackedCount} of ${detail.max_listings} tracked`],
                ['Sites', siteNames],
                ['Replicas', detail.allow_reproductions ? 'accepted' : 'skipped'],
              ].map(([key, value]) => (
                <div
                  key={key}
                  className="flex items-center justify-between gap-3 border-b border-hairline py-2"
                >
                  <dt className="font-mono text-[12px] text-ink-3">{key}</dt>
                  <dd
                    className={cn(
                      'text-right font-mono text-xs text-ink tnum',
                      key === 'Mode' && 'text-lume uppercase',
                    )}
                  >
                    {value}
                  </dd>
                </div>
              ))}
              <div className="flex items-center justify-between gap-3 py-2">
                <dt className="font-mono text-[12px] text-ink-3">Notify at target</dt>
                <dd>
                  <Switch
                    checked={detail.watch.notify}
                    onCheckedChange={(v) => notifyToggle.mutate(v)}
                    aria-label="Notify me when this item reaches its target"
                  />
                </dd>
              </div>
            </dl>
            {detail.criteria ? (
              <blockquote className="mt-2 rounded-r-sm border-l-2 border-lume-deep bg-well px-3 py-2 text-xs text-ink-2 italic">
                “{detail.criteria}”
              </blockquote>
            ) : null}
            <Button className="mt-4 w-full" onClick={() => setEditOpen(true)}>
              Edit tracking
            </Button>
            <button
              type="button"
              className="mt-3 block w-full text-center font-mono text-[12px] tracking-[0.08em] text-ink-3 uppercase hover:text-rise"
              onClick={() => setDeleteOpen(true)}
            >
              Remove item
            </button>
          </Card>
        </div>
      </div>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={(open) => {
          setDeleteOpen(open)
          if (!open) remove.reset()
        }}
        title="Remove item"
        description={`Remove “${detail.name}” from your items? Your listings and price history for it are deleted${
          instance?.vision_enabled ? ', along with the listing photos saved for it. Its reference photos stay' : ''
        }. Anyone else tracking it keeps theirs.`}
        confirmLabel="Remove item"
        pending={remove.isPending}
        error={remove.error instanceof ApiError ? remove.error.message : null}
        onConfirm={() => remove.mutate()}
      />

      <EditItemDialog
        // EditItemDialog seeds its form state from props once, so remount it
        // whenever a tracked field changes server-side (an MCP edit, or another tab).
        key={`${detail.id}-${detail.name}-${detail.target_price}-${detail.criteria}-${detail.selection_mode}-${detail.max_listings}-${detail.hunt.enabled}-${(detail.site_ids ?? []).join(',')}`}
        // the detail carries the watch's switch as hunt.enabled
        item={{ ...detail, hunt: detail.hunt.enabled }}
        open={editOpen}
        onOpenChange={setEditOpen}
        onSaved={(saved) => {
          if (saved.id !== detail.id) navigate(`/items/${saved.id}`, { replace: true })
        }}
      />
    </div>
  )
}
