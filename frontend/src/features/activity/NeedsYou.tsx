import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listJobs, listSites } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { Job, JobsSummary, PausedSite } from '@/api/types'
import { isPaused } from '@/features/sites/sitePause'
import { clockTime } from '@/lib/time'
import { HuntButton } from './HuntButton'
import { PausedSiteCard } from './PausedSiteCard'
import { pausedSiteOf, recentFailures } from './timeline'

const FAILED = { status: 'failed', kind: 'hunt', per_page: 5 } as const

/** Enough sites to see the shape of things; the Sites page has the rest. */
const SITES_SHOWN = 6

/**
 * The page's one call to action: everything a person can do something about,
 * gathered in one place so it never has to be found in the timeline. When
 * there is nothing, it says so, because an empty rail reads as "not loaded".
 */
export function NeedsYou({ summary }: { summary?: JobsSummary }) {
  const failed = useQuery({
    queryKey: qk.jobs(FAILED),
    queryFn: () => listJobs(FAILED),
  })
  const failures = recentFailures(failed.data?.data ?? [])
  const paused = summary?.paused_sites ?? []
  const count = paused.length + failures.length

  return (
    <aside aria-labelledby="needs-you" className="space-y-3">
      <div className="flex items-baseline gap-2.5">
        <h2
          id="needs-you"
          className="font-display text-[19px] font-semibold tracking-[0.08em] text-ink uppercase"
        >
          Needs you
        </h2>
        {count > 0 ? <span className="font-mono text-[12px] text-warn tnum">{count}</span> : null}
      </div>

      {summary && !failed.isLoading && count === 0 ? (
        <p className="flex items-center gap-2 rounded-lg border border-hairline bg-surface px-4 py-3 font-mono text-[12px] text-ink-2">
          <span aria-hidden className="text-drop">
            ✓
          </span>
          Nothing needs you
        </p>
      ) : null}

      {paused.map((site) => (
        <PausedSiteCard key={site.site_id} site={site} />
      ))}
      {failures.map((job) => (
        <FailureCard key={job.id} job={job} pause={pausedSiteOf(job, paused)} />
      ))}

      <SiteHealth />
    </aside>
  )
}

/** A failed hunt, with Retry. While its site is paused a retry would only queue behind the
 *  pause, so Retry is held and says until when. */
function FailureCard({ job, pause }: { job: Job; pause?: PausedSite }) {
  return (
    <div className="space-y-2.5 rounded-lg border border-rise/35 bg-rise/[0.06] p-4">
      <div className="flex items-baseline gap-2">
        <span aria-hidden className="text-rise">
          ✗
        </span>
        <p className="min-w-0 flex-1 text-sm font-semibold break-words text-ink">
          {job.item_name}
          {job.site_name ? (
            <span className="font-normal text-ink-3"> × {job.site_name}</span>
          ) : null}
        </p>
        <span className="font-mono text-[12px] text-ink-3 tnum">{clockTime(job.finished_at)}</span>
      </div>
      <p className="text-[14px] leading-relaxed text-ink-2">
        Hunt failed.{job.error ? ` ${job.error}` : ''}
      </p>
      <div className="flex items-center gap-3">
        {job.item_id != null ? (
          <HuntButton
            scope="item"
            scopeId={job.item_id}
            label="Retry"
            size="sm"
            unavailable={
              pause ? `${pause.site_name} is paused until ${clockTime(pause.paused_until)}` : undefined
            }
          />
        ) : null}
        <Link
          to={`/activity/${job.id}`}
          className="font-mono text-[12px] tracking-[0.08em] text-ink-2 uppercase hover:text-lume"
        >
          Details →
        </Link>
      </div>
    </div>
  )
}

/** Paused sites first, then the busiest: the ones a bot wall would hurt most. Desktop only —
 *  on a phone the rail sits above the timeline, and this is not something that needs you. */
function SiteHealth() {
  const sites = useQuery({ queryKey: qk.sites, queryFn: listSites })
  const rows = [...(sites.data?.data ?? [])]
    .sort((a, b) => Number(isPaused(b)) - Number(isPaused(a)) || b.listing_count - a.listing_count)
    .slice(0, SITES_SHOWN)
  if (rows.length === 0) return null

  return (
    <section aria-labelledby="site-health" className="hidden space-y-2 pt-3 lg:block">
      <div className="flex items-baseline justify-between">
        <h3
          id="site-health"
          className="font-mono text-[12px] text-ink-3"
        >
          Sites
        </h3>
        <Link
          to="/sites"
          className="font-mono text-[12px] tracking-[0.08em] text-ink-3 uppercase hover:text-lume"
        >
          All →
        </Link>
      </div>
      <ul className="divide-y divide-hairline rounded-lg border border-hairline bg-surface px-4">
        {rows.map((site) => (
          <li key={site.id} className="flex items-center gap-2.5 py-2 font-mono text-[12px]">
            <span
              aria-hidden
              className={
                isPaused(site) ? 'size-1.5 rounded-full bg-warn' : 'size-1.5 rounded-full bg-drop'
              }
            />
            <span className="min-w-0 flex-1 truncate text-ink">{site.name}</span>
            {isPaused(site) ? (
              <span className="text-warn">paused</span>
            ) : (
              <span className="text-ink-3 tnum">{site.listing_count} listings</span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
