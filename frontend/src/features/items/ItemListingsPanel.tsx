import { useQuery } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'
import { getItem } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { Skeleton } from '@/components/ui/skeleton'
import { RelativeTime } from '@/components/ui/relative-time'
import { cn } from '@/lib/cn'
import { formatMoney } from '@/lib/money'
import { MatchPill } from './MatchPill'

function stockText(inStock: boolean | null): string {
  return inStock == null ? 'stock unknown' : inStock ? 'in stock' : 'out of stock'
}

/**
 * The "all the options" view: an item row's tracked listings, rendered inline
 * inside an expanded table row on the category page. Lazy — fetches the item
 * detail on first expand.
 */
export function ItemListingsPanel({ itemId }: { itemId: number }) {
  const item = useQuery({ queryKey: qk.item(itemId), queryFn: () => getItem(itemId) })

  if (item.isLoading) {
    return (
      <div className="space-y-1.5 py-1">
        <Skeleton className="h-5" />
        <Skeleton className="h-5" />
      </div>
    )
  }

  const listings = (item.data?.listings ?? []).filter((l) => l.active)
  if (listings.length === 0) {
    return (
      <p className="py-2 text-xs text-ink-3">
        {item.data?.criteria
          ? "No listings met your criteria yet. Loosen them, or choose Hunt now from this row's menu to try again."
          : "No tracked listings yet. Snagr is hunting for some, or choose Hunt now from this row's menu."}
      </p>
    )
  }

  const sorted = [...listings].sort((a, b) => {
    const scoreDiff = (b.match_score ?? -1) - (a.match_score ?? -1)
    if (scoreDiff !== 0) return scoreDiff
    return Number(a.latest_price ?? Infinity) - Number(b.latest_price ?? Infinity)
  })

  return (
    <div className="divide-y divide-hairline/60">
      {sorted.map((listing) => (
        <div key={listing.id} className="flex items-center gap-3 py-1.5 text-xs">
          <a
            href={listing.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex min-w-0 flex-1 items-center gap-1 text-ink-2 hover:text-ink hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            <span className="truncate">{listing.title ?? listing.url.replace(/^https?:\/\/(www\.)?/, '')}</span>
            <ExternalLink className="size-3 shrink-0 text-ink-3" />
          </a>
          <span className="shrink-0 text-ink-3">{listing.site_name}</span>
          <MatchPill score={listing.match_score} summary={listing.match_summary} />
          <span className="w-20 shrink-0 text-right font-mono text-ink tnum">
            {formatMoney(listing.latest_price)}
          </span>
          {listing.in_stock === false ? (
            <span className="shrink-0 font-mono text-[12px] text-rise">out of stock</span>
          ) : null}
          <span className="flex w-16 shrink-0 items-center gap-1 text-ink-3">
            {/* out of stock is spelled out beside the price; in stock (filled) and unknown (hollow) differ by shape */}
            <span
              title={listing.in_stock === false ? undefined : stockText(listing.in_stock)}
              className={cn(
                'size-1.5 shrink-0 rounded-full',
                listing.in_stock == null ? 'border border-ink-3' : listing.in_stock ? 'bg-drop' : 'invisible',
              )}
            >
              {listing.in_stock === false ? null : <span className="sr-only">{stockText(listing.in_stock)}</span>}
            </span>
            <RelativeTime iso={listing.last_checked_at} />
          </span>
        </div>
      ))}
    </div>
  )
}
