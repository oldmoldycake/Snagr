import { useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { getPriceHistory, updateListing } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ItemDetail, Listing } from '@/api/types'
import { chart } from '@/components/charts/chartTheme'
import { Badge } from '@/components/ui/badge'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/cn'
import { formatMoney, fromCents, toCents } from '@/lib/money'
import { RANGE_LABELS, relativeTime, type TimeRange } from '@/lib/time'
import { MatchPill } from './MatchPill'
import { prepareSeries } from './seriesPrep'

/** Below the pill's amber band — still tracked, but folded off the front page. */
const FOLD_SCORE = 70
/** Sub-$1 drift renders as a bare dot — no false motion. */
const UNCHANGED_CENTS = 100
const STALE_MS = 24 * 3_600_000
/** Past this rail position, price labels flip to the left of their dot. */
const LABEL_FLIP_PCT = 78

/** Row/axis strips must share one grid so the rail column lines up. */
const GRID_COLS = 'grid-cols-[minmax(0,1fr)_100px_34px] sm:grid-cols-[minmax(170px,4fr)_minmax(180px,5fr)_100px_34px]'
const COL_LABEL = 'font-mono text-[10px] font-medium tracking-[0.13em] text-ink-3 uppercase'

interface Rail {
  /** Rail position for a price in cents: high (pricier) left → target right. */
  place: (cents: number) => { pct: number; clamp: '«' | '»' | null }
  targetPct: number | null
}

function makeRail(mainRows: Listing[], startCents: Map<number, number>, targetC: number | null): Rail | null {
  const cents: number[] = []
  for (const l of mainRows) {
    const now = toCents(l.latest_price)
    if (now != null) cents.push(now)
    const start = startCents.get(l.id)
    if (start != null) cents.push(start)
  }
  if (targetC != null) cents.push(targetC)
  if (cents.length === 0) return null

  // Domain covers the unfolded rows + target; opened folded rows may clamp.
  const hi = Math.max(...cents)
  const lo = Math.min(...cents)
  const pad = Math.max(Math.round((hi - lo) * 0.04), 200)
  const left = hi + pad
  const right = lo - pad
  const place = (c: number) => {
    const raw = ((left - c) / (left - right)) * 100
    return {
      pct: Math.max(0, Math.min(100, raw)),
      clamp: raw < 0 ? ('«' as const) : raw > 100 ? ('»' as const) : null,
    }
  }
  return { place, targetPct: targetC != null ? place(targetC).pct : null }
}

function stockText(listing: Listing): string {
  return listing.in_stock == null ? 'stock unknown' : listing.in_stock ? 'in stock' : 'out of stock'
}

/**
 * Health is silence — only abnormal states earn a chip on the title line.
 * State only, no timestamp: the chip competes with the title for width, and
 * "checked Xm ago" is one expand-click away.
 */
function exceptionChip(listing: Listing): string | null {
  if (listing.latest_status === 'error') return 'check failed'
  if (listing.in_stock === false) return 'out of stock'
  if (listing.last_checked_at && Date.now() - new Date(listing.last_checked_at).getTime() > STALE_MS)
    return 'stale'
  return null
}

function AxisStrip({
  rail,
  target,
  currency,
  range,
}: {
  rail: Rail | null
  target: string | null
  currency: string
  range: TimeRange
}) {
  return (
    <div className={cn('hidden items-end gap-3 px-4 pt-1.5 pb-1 sm:grid', GRID_COLS)}>
      <span className={COL_LABEL}>Listing</span>
      <div className="relative pt-3.5">
        {rail ? (
          <span className="absolute top-0 left-0 font-mono text-[10px] text-ink-3">
            ◂ pricier · drift {RANGE_LABELS[range]}
          </span>
        ) : null}
        {rail?.targetPct != null ? (
          <span
            className="absolute top-0 font-mono text-[10px] whitespace-nowrap text-drop"
            style={
              // right-anchor near the edge so the label can't spill out of the column
              rail.targetPct > 82
                ? { right: 0 }
                : { left: `${rail.targetPct}%`, transform: 'translateX(-50%)' }
            }
          >
            ⌖ {formatMoney(target, currency)}
          </span>
        ) : null}
        {/* graduated ruler — same treatment as the header Ladder, so both rails read as one instrument */}
        <div
          className="h-3.5"
          style={{
            backgroundImage:
              'linear-gradient(var(--color-hairline-strong), var(--color-hairline-strong)), repeating-linear-gradient(90deg, var(--color-hairline-strong) 0 1px, transparent 1px 10%)',
            backgroundSize: '100% 1px, 100% 6px',
            backgroundPosition: '0 9px, 0 6px',
            backgroundRepeat: 'no-repeat',
          }}
        />
      </div>
      <span className={cn(COL_LABEL, 'text-right')}>vs ⌖</span>
      <span className={COL_LABEL}>Fit</span>
    </div>
  )
}

function Track({
  listing,
  color,
  startC,
  rail,
  targetC,
  currency,
}: {
  listing: Listing
  color: string
  startC: number | null
  rail: Rail | null
  targetC: number | null
  currency: string
}) {
  const nowC = toCents(listing.latest_price)
  const zone =
    rail?.targetPct != null ? (
      <span
        aria-hidden
        className="absolute inset-y-0.5 border-l border-dashed border-drop/50 bg-drop/10"
        style={{ left: `${rail.targetPct}%`, right: 0 }}
      />
    ) : null

  if (rail == null || nowC == null) {
    return (
      <div aria-hidden className="relative hidden h-7 sm:block">
        {zone}
        <span className="absolute inset-x-0 top-[19px] h-px bg-overlay" />
      </div>
    )
  }

  const now = rail.place(nowC)
  const moved = startC != null && Math.abs(nowC - startC) >= UNCHANGED_CENTS
  const start = moved ? rail.place(startC) : null
  const falling = start != null && startC != null && startC > nowC
  const under = targetC != null && nowC <= targetC

  return (
    <div aria-hidden className="relative hidden h-7 sm:block">
      {zone}
      <span className="absolute inset-x-0 top-[19px] h-px bg-overlay" />
      {start ? (
        <>
          <span className="absolute top-3.5 h-2.5 w-px bg-ink-3" style={{ left: `${start.pct}%` }} />
          <span
            className={cn('absolute top-[18px] h-[2px]', falling ? 'bg-drop/55' : 'bg-rise/55')}
            style={{
              left: `${Math.min(start.pct, now.pct)}%`,
              width: `${Math.abs(now.pct - start.pct)}%`,
            }}
          />
          {falling ? (
            <span
              className="absolute top-[15px] h-0 w-0 border-y-4 border-y-transparent border-l-[6px] border-l-drop/85"
              style={{ left: `calc(${now.pct}% - 11px)` }}
            />
          ) : (
            <span
              className="absolute top-[15px] h-0 w-0 border-y-4 border-y-transparent border-r-[6px] border-r-rise/85"
              style={{ left: `calc(${now.pct}% + 5px)` }}
            />
          )}
        </>
      ) : null}
      <span
        className="absolute top-[15px] size-2 -translate-x-1/2 rounded-full border-2 border-surface"
        style={{ left: `${now.pct}%`, background: color }}
      />
      {now.clamp ? (
        <span
          className="absolute top-3 font-mono text-[10px] text-ink-3"
          style={now.clamp === '»' ? { right: 0 } : { left: 0 }}
        >
          {now.clamp}
        </span>
      ) : null}
      <span
        className={cn(
          'absolute top-0 font-mono text-[10px] font-semibold whitespace-nowrap tnum',
          under ? 'text-drop' : 'text-ink',
        )}
        style={
          now.pct > LABEL_FLIP_PCT
            ? { left: `calc(${now.pct}% - 9px)`, transform: 'translateX(-100%)' }
            : { left: `calc(${now.pct}% + 9px)` }
        }
      >
        {formatMoney(listing.latest_price, currency)}
      </span>
    </div>
  )
}

function DeltaCell({
  listing,
  targetC,
  currency,
}: {
  listing: Listing
  targetC: number | null
  currency: string
}) {
  const nowC = toCents(listing.latest_price)
  const diff = nowC != null && targetC != null ? nowC - targetC : null
  return (
    <div className="text-right">
      {/* below sm the rail is gone, so the price returns as text */}
      <p className="font-mono text-[13px] font-semibold text-ink tnum sm:hidden">
        {formatMoney(listing.latest_price, currency)}
      </p>
      {diff == null ? (
        <p className="font-mono text-[11px] text-ink-3">—</p>
      ) : diff <= 0 ? (
        <p className="font-mono text-[11px] whitespace-nowrap text-drop tnum">
          ✓ {formatMoney(fromCents(-diff), currency)} under
        </p>
      ) : (
        <p className="font-mono text-[11px] whitespace-nowrap text-ink-3 tnum">
          +{formatMoney(fromCents(diff), currency)}
        </p>
      )}
    </div>
  )
}

function ExpandedRow({
  listing,
  detail,
  startC,
  range,
}: {
  listing: Listing
  detail: ItemDetail
  startC: number | null
  range: TimeRange
}) {
  const queryClient = useQueryClient()
  const toggle = useMutation({
    mutationFn: (active: boolean) => updateListing(listing.id, { active }),
    // optimistic: flip immediately, roll back on error
    onMutate: async (active) => {
      await queryClient.cancelQueries({ queryKey: qk.item(detail.id) })
      const prev = queryClient.getQueryData<ItemDetail>(qk.item(detail.id))
      if (prev) {
        queryClient.setQueryData<ItemDetail>(qk.item(detail.id), {
          ...prev,
          listings: prev.listings.map((l) => (l.id === listing.id ? { ...l, active } : l)),
        })
      }
      return { prev }
    },
    onError: (_err, _active, ctx) => {
      if (ctx?.prev) queryClient.setQueryData(qk.item(detail.id), ctx.prev)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['items'] })
    },
  })

  const nowC = toCents(listing.latest_price)
  const moved = startC != null && nowC != null && Math.abs(nowC - startC) >= UNCHANGED_CENTS
  const fell = moved && nowC != null && startC != null && nowC < startC

  return (
    <div className="flex items-start gap-4 bg-well py-3 pr-4 pl-10">
      <p className="min-w-0 flex-1 font-mono text-[11px] leading-relaxed text-ink-3">
        {listing.match_score != null ? (
          <>
            <span className="text-ink-2">match {listing.match_score}</span>
            {listing.match_summary ? <> — {listing.match_summary}</> : null}
          </>
        ) : (
          'not scored yet'
        )}
        <br />
        {moved && startC != null && nowC != null ? (
          <>
            started <span className="text-ink-2 tnum">{formatMoney(fromCents(startC), detail.currency)}</span>
            {' · '}
            <span className={cn('tnum', fell ? 'text-drop' : 'text-rise')}>
              {fell ? '▼' : '▲'} {formatMoney(fromCents(Math.abs(nowC - startC)), detail.currency)} over{' '}
              {RANGE_LABELS[range]}
            </span>
            {' · '}
          </>
        ) : startC != null ? (
          <>unchanged over {RANGE_LABELS[range]} · </>
        ) : null}
        {stockText(listing)} · checked {relativeTime(listing.last_checked_at)} · {listing.site_name} ·{' '}
        {listing.discovered_by_run_id != null ? (
          <Link to={`/runs/${listing.discovered_by_run_id}`} className="hover:text-ink hover:underline">
            found {relativeTime(listing.created_at)}
          </Link>
        ) : (
          <>found {relativeTime(listing.created_at)}</>
        )}
        {' · '}
        <a href={listing.url} target="_blank" rel="noreferrer" className="text-ink-2 hover:text-lume">
          open listing ↗
        </a>
      </p>
      <label className="flex shrink-0 items-center gap-2 font-mono text-[10px] tracking-[0.08em] text-ink-3 uppercase">
        active
        <Switch
          checked={listing.active}
          onCheckedChange={(active) => toggle.mutate(active)}
          aria-label={`${listing.active ? 'Deactivate' : 'Activate'} ${listing.site_name} listing`}
        />
      </label>
    </div>
  )
}

function BoardRow({
  listing,
  detail,
  rail,
  color,
  startC,
  targetC,
  isBestMatch,
  dimmed,
  expanded,
  onToggle,
  range,
}: {
  listing: Listing
  detail: ItemDetail
  rail: Rail | null
  color: string
  startC: number | null
  targetC: number | null
  isBestMatch: boolean
  dimmed: boolean
  expanded: boolean
  onToggle: () => void
  range: TimeRange
}) {
  const soldOrEnded =
    !listing.active && (listing.latest_status === 'sold' || listing.latest_status === 'ended')
  const chip = listing.active ? exceptionChip(listing) : null

  return (
    <>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={expanded}
        onClick={onToggle}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault()
            onToggle()
          }
        }}
        className={cn(
          'group grid cursor-pointer items-center gap-3 px-4 py-2 transition-colors',
          GRID_COLS,
          expanded ? 'bg-raised' : 'hover:bg-raised/60',
          dimmed && 'opacity-45',
        )}
      >
        <div className="flex min-w-0 items-center gap-2">
          <span
            aria-hidden
            className={cn(
              'shrink-0 font-mono text-[10px]',
              expanded
                ? 'text-lume'
                : 'text-ink-3 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100',
            )}
          >
            {expanded ? '▾' : '▸'}
          </span>
          <a
            href={listing.url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="min-w-0 truncate text-[13px] font-medium text-ink hover:text-lume hover:underline"
          >
            {listing.title ?? listing.url.replace(/^https?:\/\/(www\.)?/, '')}
          </a>
          {isBestMatch ? (
            <Badge variant="lume" className="shrink-0">
              Best match
            </Badge>
          ) : null}
          {soldOrEnded ? (
            <Badge variant="warn" className="shrink-0">
              {listing.latest_status === 'sold' ? 'Sold' : 'Ended'} · {relativeTime(listing.last_checked_at)}
            </Badge>
          ) : null}
          {chip ? (
            <Badge variant="warn" className="shrink-0 font-mono text-[10px]">
              {chip}
            </Badge>
          ) : null}
        </div>
        <Track
          listing={listing}
          color={color}
          startC={startC}
          rail={rail}
          targetC={targetC}
          currency={detail.currency}
        />
        <DeltaCell listing={listing} targetC={targetC} currency={detail.currency} />
        <MatchPill score={listing.match_score} summary={listing.match_summary} quietMid />
      </div>
      {expanded ? <ExpandedRow listing={listing} detail={detail} startC={startC} range={range} /> : null}
    </>
  )
}

/**
 * The listings "target board": one price rail per listing, running range-high
 * (left) → target ⌖ (right) like the header Ladder, with drift marks from the
 * chart's selected range. Healthy rows stay quiet; the rationale, drift
 * detail, and active switch live in the click-to-expand row.
 */
export function ListingsBoard({ detail, range }: { detail: ItemDetail; range: TimeRange }) {
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [foldOpen, setFoldOpen] = useState(false)

  // Same key as ChartPanel's per-listing tab — React Query shares the fetch.
  const history = useQuery({
    queryKey: qk.itemHistory(detail.id, range),
    queryFn: () => getPriceHistory(detail.id, range),
    placeholderData: keepPreviousData,
  })

  const prep = useMemo(() => (history.data ? prepareSeries(history.data) : null), [history.data])
  const colorOf = (listingId: number) => prep?.colorOf(listingId) ?? chart.othersGray

  // Price at the start of the selected range, per listing — the drift origin.
  const startCents = useMemo(() => {
    const m = new Map<number, number>()
    for (const s of history.data?.series ?? []) {
      let first: { t: number; c: number } | null = null
      for (const p of s.points) {
        const t = new Date(p.ts).getTime()
        const c = toCents(p.price)
        if (c == null || !Number.isFinite(t)) continue
        if (!first || t < first.t) first = { t, c }
      }
      if (first) m.set(s.listing_id, first.c)
    }
    return m
  }, [history.data])

  const target = detail.watch.target_price ?? detail.target_price
  const targetC = toCents(target)
  const mode = detail.selection_mode

  const byMode = (a: Listing, b: Listing) => {
    const priceDiff = Number(a.latest_price ?? Infinity) - Number(b.latest_price ?? Infinity)
    if (mode !== 'best_match') return priceDiff
    return (b.match_score ?? -1) - (a.match_score ?? -1) || priceDiff
  }
  const active = [...detail.listings].filter((l) => l.active).sort(byMode)
  const inactive = [...detail.listings].filter((l) => !l.active).sort(byMode)

  // best-match mode folds the low-scoring tail — but never the whole list
  let main = active
  let lowMatch: Listing[] = []
  if (mode === 'best_match') {
    const cleared = active.filter((l) => (l.match_score ?? -1) >= FOLD_SCORE)
    if (cleared.length > 0 && cleared.length < active.length) {
      main = cleared
      lowMatch = active.filter((l) => (l.match_score ?? -1) < FOLD_SCORE)
    }
  }
  const folded = [...lowMatch, ...inactive]

  // badge the highest-scoring tracked listing (price breaks ties) in best_match mode
  const bestMatchId = mode === 'best_match' ? (active.find((l) => l.match_score != null)?.id ?? null) : null

  const rail = makeRail(main, startCents, targetC)

  const soldCount = inactive.filter(
    (l) => l.latest_status === 'sold' || l.latest_status === 'ended',
  ).length
  const foldLabel = [
    `${folded.length} more`,
    lowMatch.length > 0 ? `${lowMatch.length} lower match` : null,
    soldCount > 0 ? `${soldCount} sold` : null,
    inactive.length - soldCount > 0 ? `${inactive.length - soldCount} inactive` : null,
  ]
    .filter(Boolean)
    .join(' · ')

  const row = (listing: Listing, dimmed: boolean) => (
    <BoardRow
      key={listing.id}
      listing={listing}
      detail={detail}
      rail={rail}
      color={colorOf(listing.id)}
      startC={startCents.get(listing.id) ?? null}
      targetC={targetC}
      isBestMatch={bestMatchId === listing.id}
      dimmed={dimmed}
      expanded={expandedId === listing.id}
      onToggle={() => setExpandedId((id) => (id === listing.id ? null : listing.id))}
      range={range}
    />
  )

  return (
    <div>
      <AxisStrip rail={rail} target={target} currency={detail.currency} range={range} />
      <div className="divide-y divide-hairline border-t border-hairline">
        {main.map((l) => row(l, false))}
      </div>
      {folded.length > 0 ? (
        <Collapsible open={foldOpen} onOpenChange={setFoldOpen}>
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-3 bg-well px-4 py-1.5 font-mono text-[10.5px] tracking-[0.08em] text-ink-3 uppercase before:h-px before:flex-1 before:bg-hairline-strong before:content-[''] after:h-px after:flex-1 after:bg-hairline-strong after:content-[''] hover:text-ink-2"
            >
              {foldLabel} — {foldOpen ? 'hide' : 'show'}
            </button>
          </CollapsibleTrigger>
          <CollapsibleContent>
            <div className="divide-y divide-hairline border-t border-hairline">
              {folded.map((l) => row(l, !l.active))}
            </div>
          </CollapsibleContent>
        </Collapsible>
      ) : null}
    </div>
  )
}
