import { useQuery } from '@tanstack/react-query'
import { getJobsSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { cn } from '@/lib/cn'
import { ChecksTail } from './ChecksTail'
import { HistoryTable } from './HistoryTable'
import { HunterHero } from './HunterHero'
import { LiveHunts } from './LiveHunts'
import { NextUp } from './NextUp'
import { PausedSiteBanner } from './PausedSiteBanner'
import { useJobs } from './JobsProvider'

/** The summary is cheap and its numbers age visibly (a countdown), so it is
 *  polled as well as invalidated on every frame. */
const SUMMARY_POLL_MS = 30_000

/**
 * What the hunter is doing, in the dashboard's three beats: a sentence, the
 * live work, then the ledger. Nothing here repeats a per-item fact the item
 * page shows — the hero aggregates, and the one per-listing detail is the
 * checks tail.
 */
export function ActivityPage() {
  const { connection } = useJobs()
  const summary = useQuery({
    queryKey: qk.jobsSummary,
    queryFn: getJobsSummary,
    refetchInterval: SUMMARY_POLL_MS,
  })

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3">
        <h1 className="font-display text-[26px] leading-tight font-semibold tracking-[0.05em] text-ink uppercase">
          Activity
        </h1>
        <span className="flex items-center gap-1.5 font-mono text-[11px] text-ink-3">
          <span
            aria-hidden
            className={cn(
              'size-1.5 rounded-full',
              connection === 'live' ? 'bg-drop' : 'animate-pulse bg-warn',
            )}
          />
          {connection === 'live' ? 'live' : 'reconnecting…'}
        </span>
      </div>

      <HunterHero summary={summary.data} />

      {(summary.data?.paused_sites ?? []).map((site) => (
        <PausedSiteBanner key={site.site_id} site={site} />
      ))}

      <LiveHunts />
      <ChecksTail summary={summary.data} />
      <NextUp summary={summary.data} />
      <HistoryTable />
    </div>
  )
}
