import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listRuns } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ItemSummary, PriceDrop } from '@/api/types'
import { effectiveTarget, isFreshDrop } from '@/features/items/WatchList'
import { formatMoney, fromCents, toCents } from '@/lib/money'

/**
 * Beat one of the dashboard: the app states the hunt's status in a sentence,
 * then one line of tonight's totals. Aggregates only — per-item facts live in
 * the table, so nothing here can repeat a row (the "once only" rule).
 */
export function VerdictHero({
  items,
  drops,
  className,
}: {
  items: ItemSummary[]
  /** newest recent drop per item id — the same map the table's chips use */
  drops: Map<number, PriceDrop>
  className?: string
}) {
  const snagged = items.filter((item) => item.target_met)

  let closest: { item: ItemSummary; gapCents: number; ratio: number } | null = null
  for (const item of items) {
    if (item.target_met) continue
    const best = toCents(item.best_price)
    const target = toCents(effectiveTarget(item))
    if (best == null || target == null || target <= 0) continue
    const gapCents = best - target
    const ratio = gapCents / target
    if (closest == null || ratio < closest.ratio) closest = { item, gapCents, ratio }
  }

  const eyebrow = `Tonight · ${new Date().toLocaleDateString('en-US', {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
  })}`

  return (
    <section className={className}>
      <p className="font-mono text-[10.5px] tracking-[0.16em] text-ink-3 uppercase">{eyebrow}</p>

      {snagged.length > 0 ? (
        <h1 className="mt-3 font-display text-[42px] leading-[1.05] font-semibold tracking-[0.015em] text-drop text-balance">
          {snagged.length} in range
          <span aria-hidden className="ml-1 align-[4px] text-3xl">
            ⌖
          </span>
        </h1>
      ) : (
        <h1 className="mt-3 font-display text-[42px] leading-[1.05] font-semibold tracking-[0.015em] text-ink-2 text-balance">
          Nothing in range yet
        </h1>
      )}

      {closest ? (
        <p className="mt-2.5 text-base text-ink-2">
          {snagged.length > 0 ? 'Next closest: ' : 'Closest: '}
          <Link to={`/items/${closest.item.id}`} className="font-semibold text-ink hover:text-lume">
            {closest.item.name}
          </Link>{' '}
          is{' '}
          <span className="font-mono text-[15px] font-semibold text-lume tnum">
            {formatMoney(fromCents(closest.gapCents), closest.item.currency)}
          </span>{' '}
          from striking.
        </p>
      ) : snagged.length === 0 ? (
        <p className="mt-2.5 text-base text-ink-2">
          No prices yet — run a sweep to get eyes on your targets.
        </p>
      ) : null}

      <PulseLine items={items} drops={drops} />
    </section>
  )
}

/**
 * Tonight's totals: counts and money only, never item names. The strike/drop
 * split, and the money shaved, come from the drops the page already fetched;
 * new-listings/checked come from the ticker's own last-run query (same key,
 * so React Query dedupes). Hidden until the agent has run at least once.
 */
function PulseLine({ items, drops }: { items: ItemSummary[]; drops: Map<number, PriceDrop> }) {
  const lastRun = useQuery({
    queryKey: qk.runs({ per_page: 1 }),
    queryFn: () => listRuns({ per_page: 1 }),
  })

  const stats = lastRun.data?.data[0]?.stats
  if (lastRun.data == null || lastRun.data.data.length === 0) return null

  const snaggedIds = new Set(items.filter((item) => item.target_met).map((item) => item.id))
  let struck = 0
  let dropped = 0
  let shavedCents = 0
  let currency = 'USD'
  for (const [itemId, drop] of drops) {
    if (!isFreshDrop(drop)) continue
    const oldCents = toCents(drop.old_price)
    const newCents = toCents(drop.new_price)
    if (oldCents != null && newCents != null) shavedCents += oldCents - newCents
    currency = drop.currency
    if (snaggedIds.has(itemId)) struck += 1
    else dropped += 1
  }

  const quiet = struck === 0 && dropped === 0
  return (
    <p className="mt-4.5 flex flex-wrap items-baseline gap-x-5 gap-y-1.5 font-mono text-xs text-ink-2 tnum">
      <span className="text-[10.5px] tracking-[0.1em] text-ink-3 uppercase">Tonight</span>
      {quiet ? <span>no movement</span> : null}
      {struck > 0 ? (
        <span className="text-drop">
          <span aria-hidden>⌖</span> <b className="font-semibold text-ink">{struck}</b> struck
        </span>
      ) : null}
      {dropped > 0 ? (
        <span>
          <span aria-hidden className="text-drop">
            ▼
          </span>{' '}
          <b className="font-semibold text-ink">{dropped}</b> {dropped === 1 ? 'drop' : 'drops'}
        </span>
      ) : null}
      {shavedCents > 0 ? (
        <span>
          <b className="font-semibold text-ink">{formatMoney(fromCents(shavedCents), currency)}</b>{' '}
          shaved
        </span>
      ) : null}
      {stats && stats.new_listings > 0 ? (
        <span>
          <b className="font-semibold text-ink">{stats.new_listings}</b> new{' '}
          {stats.new_listings === 1 ? 'listing' : 'listings'}
        </span>
      ) : null}
      {stats ? (
        <span>
          <b className="font-semibold text-ink">{stats.listings_checked}</b> checked
        </span>
      ) : null}
    </p>
  )
}
