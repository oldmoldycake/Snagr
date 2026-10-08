import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { getJobsSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { ItemDetail } from '@/api/types'
import { useInstance } from '@/features/auth/useSession'
import { clockTime, countdown, formatDuration, formatInterval } from '@/lib/time'
import { useJobs } from './JobsProvider'
import { trackingCount, trackingLine } from './trackingLine'

/**
 * What the hunter will do next for this item, in two lines: price checks,
 * then hunting. Everything in it is computed from the item's jobs and
 * listings — there is no state here that could disagree with the Activity page.
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

  const huntingOff = useInstance().data?.hunt_enabled === false
  const summary = useQuery({ queryKey: qk.jobsSummary, queryFn: getJobsSummary })
  const paused = (summary.data?.paused_sites ?? []).find((site) =>
    detail.listings.some((listing) => listing.site_id === site.site_id),
  )
  const tracked = detail.listings.filter((listing) => listing.active).length

  return (
    <>
      <p className="mt-1 font-mono text-[12px] text-ink-3 tnum">
        {paused ? (
          <>
            <span aria-hidden className="text-warn">
              ⚠
            </span>{' '}
            <span className="text-warn">
              {paused.site_name} paused until{' '}
              {clockTime(paused.paused_until)}
            </span>
            {' · '}
          </>
        ) : null}
        price checks every {formatInterval(detail.recheck.interval_minutes)} ·{' '}
        {detail.recheck.running > 0
          ? `${detail.recheck.running} running now`
          : `next ${countdown(detail.recheck.next_at)}`}
      </p>
      {live ? (
        <p className="mt-1 font-mono text-[12px] text-lume tnum">
          <span aria-hidden className="mr-1">
            ●
          </span>
          hunting {live.site_name ?? 'now'} · {formatDuration(live.started_at)} ·{' '}
          {trackingCount(tracked, detail.max_listings)}
        </p>
      ) : (
        <p className="mt-1 font-mono text-[12px] text-ink-3 tnum">{trackingLine(detail, tracked, huntingOff)}</p>
      )}
    </>
  )
}
