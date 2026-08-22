import { Link } from 'react-router-dom'
import type { ItemSummary } from '@/api/types'
import { effectiveTarget } from '@/features/items/WatchList'
import { formatMoney, fromCents, toCents } from '@/lib/money'
import { relativeTime } from '@/lib/time'

/**
 * Beat one of the dashboard: the app states the hunt's status in a sentence,
 * then shows only the snag-now cards. Green is reserved for "in range".
 */
export function VerdictHero({ items, className }: { items: ItemSummary[]; className?: string }) {
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

      {snagged.length > 0 ? (
        <div className="mt-6 grid gap-3.5 sm:grid-cols-2">
          {snagged.map((item) => (
            <Link
              key={item.id}
              to={`/items/${item.id}`}
              className="flex items-center gap-4 rounded-md border border-drop/30 bg-drop-dim px-4.5 py-4 transition-colors hover:border-drop/60"
            >
              <span aria-hidden className="text-lg text-drop">
                ⌖
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-ink">{item.name}</span>
                <span className="mt-0.5 block font-mono text-[11px] text-ink-3">
                  {item.best_site_name ?? '—'} · {relativeTime(item.last_checked_at)}
                </span>
              </span>
              <span className="text-right">
                <span className="block font-display text-[28px] leading-none font-bold text-drop tnum">
                  {formatMoney(item.best_price, item.currency)}
                </span>
                <span className="mt-1 block font-mono text-[11px] text-ink-3">
                  target {formatMoney(effectiveTarget(item), item.currency)}
                </span>
              </span>
              <span
                aria-hidden
                className="ml-1 shrink-0 rounded-sm bg-drop px-2.5 py-1.5 font-mono text-[11px] font-semibold tracking-[0.06em] text-[#10150e]"
              >
                VIEW →
              </span>
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  )
}
