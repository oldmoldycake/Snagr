import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getJobsSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ItemDetail } from '@/api/types'
import { cn } from '@/lib/cn'
import { countdown, formatDuration, relativeTime } from '@/lib/time'
import { useJobs } from './JobsProvider'

/**
 * What the hunter will do next for this item, in one line: checks on the
 * left, hunting on the right. Everything in it is computed from the item's
 * jobs — there is no state here that could disagree with the Activity page.
 */
export function HunterLine({ detail }: { detail: ItemDetail }) {
  const { liveHuntFor } = useJobs()
  const live = liveHuntFor('item', detail.id)
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!live) return
    const id = setInterval(() => setTick((n) => n + 1), 1000)
    return () => clearInterval(id)
  }, [live])

  const summary = useQuery({ queryKey: qk.jobsSummary, queryFn: getJobsSummary })
  const paused = (summary.data?.paused_sites ?? []).find((site) =>
    detail.listings.some((listing) => listing.site_id === site.site_id),
  )

  if (live) {
    return (
      <p className="mt-1 font-mono text-[11px] text-lume tnum">
        <span aria-hidden className="mr-1">
          ●
        </span>
        hunting {live.site_name ?? 'now'} · {formatDuration(live.started_at)} ·{' '}
        {detail.hunt.slots_open} of {detail.max_listings} slots open
      </p>
    )
  }

  return (
    <p className="mt-1 font-mono text-[11px] text-ink-3 tnum">
      {paused ? (
        <>
          <span aria-hidden className="text-warn">
            ⚠
          </span>{' '}
          <span className="text-warn">
            {paused.site_name} paused until{' '}
            {new Date(paused.paused_until).toLocaleTimeString('en-US', {
              hour12: false,
              hour: '2-digit',
              minute: '2-digit',
            })}
          </span>
          {' · '}
        </>
      ) : null}
      <span>checks</span> every {detail.recheck.interval_minutes}m ·{' '}
      {detail.recheck.running > 0
        ? `${detail.recheck.running} running now`
        : `next ${countdown(detail.recheck.next_at)}`}
      <span aria-hidden className="mx-2">
        │
      </span>
      <span className={cn(detail.hunt.slots_open === 0 && 'text-ink-3')}>hunting</span>{' '}
      {huntingHalf(detail)}
    </p>
  )
}

/** What the last hunt came to. ItemDetail carries the outcome, not the
 *  count — the count is on the job, one click away in the History table. */
const LAST_RESULT = {
  found: 'found a listing',
  nothing: 'nothing new',
  failed: 'failed',
  cancelled: 'cancelled',
} as const

function huntingHalf(detail: ItemDetail): string {
  const { hunt } = detail
  const full = hunt.slots_open === 0
  const slots = full
    ? `${detail.max_listings} of ${detail.max_listings} slots filled · waiting for one to free`
    : `${hunt.slots_open} of ${detail.max_listings} slots open`
  if (hunt.last_at == null || hunt.last_result == null) return slots
  // a full watch was never going to save anything, so "nothing new" would be
  // describing the rule rather than the hunt
  const outcome =
    full && hunt.last_result === 'nothing' ? 'nothing better' : LAST_RESULT[hunt.last_result]
  return `${slots} · last hunt ${relativeTime(hunt.last_at)}, ${outcome}`
}
