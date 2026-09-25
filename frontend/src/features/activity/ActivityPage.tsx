import { useQuery } from '@tanstack/react-query'
import { getJobsSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { HunterHero } from './HunterHero'
import { NeedsYou } from './NeedsYou'
import { Timeline } from './Timeline'
import { useJobs } from './JobsProvider'

/** The summary is cheap and its numbers age visibly (a countdown), so it is
 *  polled as well as invalidated on every frame. */
const SUMMARY_POLL_MS = 30_000

/**
 * What the hunter is doing, answered in the order people ask: is it working
 * (the hero), does anything need me (the rail), and what is it doing, about
 * to do and done (the timeline). On a phone the rail comes first, because it
 * is the only part that asks something of the reader.
 */
export function ActivityPage() {
  const { connection } = useJobs()
  const summary = useQuery({
    queryKey: qk.jobsSummary,
    queryFn: getJobsSummary,
    refetchInterval: SUMMARY_POLL_MS,
  })

  return (
    <div className="space-y-8">
      <HunterHero summary={summary.data} connection={connection} />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_300px] lg:items-start">
        <div className="lg:order-2 lg:sticky lg:top-20">
          <NeedsYou summary={summary.data} />
        </div>
        <div className="lg:order-1">
          <Timeline summary={summary.data} />
        </div>
      </div>
    </div>
  )
}
