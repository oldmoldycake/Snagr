import { useEffect, useMemo, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { isNotFound } from '@/api/client'
import { cancelJob, getJob, getJobEvents, listUsers } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { AdminUser, Job, JobEvent, JobKind, User } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { NotFound } from '@/components/ui/not-found'
import { Radar } from '@/components/ui/radar'
import { Skeleton } from '@/components/ui/skeleton'
import { TerminalLog } from '@/components/ui/terminal-log'
import { useSession } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { formatDateTime, formatDuration, formatTokens } from '@/lib/time'
import { usePageTitle } from '@/lib/usePageTitle'
import { JobStatusDot } from './JobStatusDot'
import { eventLine, resultText } from './lines'
import { useJobs } from './JobsProvider'

const LIVE_POLL_MS = 4000

/** What the breadcrumb calls each kind of job. */
const KIND_NAMES: Record<JobKind, string> = {
  hunt: 'Hunt',
  ground: 'Market price',
  recheck: 'Check',
}

function Stat({ label, value, tone }: { label: string; value: string | number; tone?: string }) {
  return (
    <div className="rounded-md border border-hairline bg-surface px-3.5 py-2.5">
      <p className="font-mono text-[12px] text-ink-3">{label}</p>
      <p className={cn('mt-1 font-display text-[26px] leading-none font-semibold tnum', tone ?? 'text-ink')}>
        {value}
      </p>
    </div>
  )
}

/**
 * One hunt, in full: what it was for, what it looked at, and every line it
 * wrote. Checks have no page — their whole output is the price check, which
 * the item page already shows — so a check id lands here and says so.
 */
export function JobPage() {
  const { id = '' } = useParams()
  const jobId = Number(id)
  const { live, events: liveEvents } = useJobs()
  const { data: me } = useSession()
  const queryClient = useQueryClient()
  const logRef = useRef<HTMLDivElement>(null)

  const isLive = live.some((job) => job.id === jobId)

  const job = useQuery({
    queryKey: qk.job(jobId),
    queryFn: () => getJob(jobId),
    refetchInterval: isLive ? LIVE_POLL_MS : false,
  })

  const fetched = useQuery({
    queryKey: qk.jobEvents(jobId),
    queryFn: () => getJobEvents(jobId),
    enabled: !isLive,
  })

  // an admin sees everyone's jobs, and one someone else asked for names them
  const askerId = job.data?.user_id
  const users = useQuery({
    queryKey: qk.adminUsers,
    queryFn: listUsers,
    enabled: me?.role === 'admin' && askerId != null && askerId !== me.id,
  })

  usePageTitle(job.data ? title(job.data, isLive) : isNotFound(job.error) ? 'Job not found' : undefined)

  const events: JobEvent[] = useMemo(
    () => (isLive ? (liveEvents.get(jobId) ?? []) : (fetched.data?.data ?? [])),
    [isLive, liveEvents, jobId, fetched.data],
  )

  useEffect(() => {
    if (isLive && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [isLive, events])

  const cancel = useMutation({
    mutationFn: () => cancelJob(jobId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['jobs'] }),
  })

  if (job.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48" />
      </div>
    )
  }

  if (job.isError && !isNotFound(job.error)) {
    return (
      <ErrorState
        title="Couldn't load this job"
        error={job.error}
        onRetry={() => void job.refetch()}
        retrying={job.isFetching}
      />
    )
  }

  if (!job.data) {
    return (
      <NotFound
        title="Job not found"
        description="It may have been cleaned up."
        to="/activity"
        label="Back to Activity"
      />
    )
  }

  const detail = job.data
  if (detail.kind === 'recheck') {
    return (
      <div className="space-y-5">
        <Breadcrumb job={detail} />
        <EmptyState
          title="Checks have no page"
          description="A price check's whole output is the price it read, which is on the item."
          action={
            detail.item_id ? (
              <Link
                to={`/items/${detail.item_id}`}
                className="font-mono text-[12px] tracking-[0.08em] text-ink-2 uppercase hover:text-lume"
              >
                Open the item →
              </Link>
            ) : undefined
          }
        />
      </div>
    )
  }

  // the hunter's own work (no watch behind it) is admin-only to cancel
  const canCancel =
    isLive && me != null && (me.role === 'admin' || detail.watch_id != null)

  return (
    <div className="space-y-5">
      <Breadcrumb job={detail} />
      <div className="flex items-center gap-4">
        {isLive ? <Radar size={44} glyph /> : null}
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-mono text-[12px] tracking-[0.14em] text-ink-3 uppercase">
            <JobStatusDot status={detail.status} withLabel />
            <span aria-hidden>·</span>
            <span className="tnum">{formatDateTime(detail.created_at)}</span>
            <span aria-hidden>·</span>
            <span>{askedBy(detail, me, users.data?.data)}</span>
          </p>
          <h1
            className={cn(
              'mt-1 font-display text-[26px] leading-tight font-semibold tracking-[0.03em]',
              isLive ? 'text-lume' : 'text-ink',
            )}
          >
            <Heading job={detail} isLive={isLive} />
          </h1>
          <p className="mt-0.5 font-mono text-xs text-ink-3 tnum">{subline(detail, isLive)}</p>
        </div>
        {canCancel ? (
          <Button size="sm" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
            Cancel
          </Button>
        ) : null}
      </div>

      {detail.error ? (
        <p
          role="alert"
          className="rounded-sm border border-rise/40 bg-rise/10 px-3 py-2 text-[14px] text-rise"
        >
          <span aria-hidden>✗</span> {detail.error}
        </p>
      ) : null}

      {detail.stats ? <Tiles job={detail} /> : null}

      <div
        ref={logRef}
        className="max-h-[32rem] overflow-y-auto rounded-lg border border-hairline bg-well px-4 py-3"
      >
        {!isLive && fetched.isError ? (
          <ErrorState
            className="border-0 py-4"
            title="Couldn't load the log"
            error={fetched.error}
            onRetry={() => void fetched.refetch()}
            retrying={fetched.isFetching}
          />
        ) : events.length === 0 ? (
          <p className="py-2 font-mono text-xs text-ink-3">
            {isLive || detail.status === 'pending'
              ? 'Waiting for Snagr…'
              : 'Nothing was recorded for this job.'}
          </p>
        ) : (
          <TerminalLog lines={events.map((event) => eventLine(event, detail.item_id))} />
        )}
      </div>
    </div>
  )
}

function Tiles({ job }: { job: Job }) {
  const stats = job.stats!
  const tokens = formatTokens(stats.tokens_in + stats.tokens_out)
  if (job.kind === 'ground') {
    return (
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        <Stat label="Sources read" value={stats.listings_checked} />
        <Stat label="Prices" value={stats.prices_found} />
        <Stat label="Tokens" value={tokens} />
      </div>
    )
  }
  const rejected = Math.max(0, stats.listings_checked - stats.new_listings - stats.errors)
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <Stat label="Listings looked at" value={stats.listings_checked} />
      <Stat
        label="Saved"
        value={stats.new_listings}
        tone={stats.new_listings > 0 ? 'text-lume' : undefined}
      />
      <Stat label="Rejected" value={rejected} />
      <Stat label="Tokens" value={tokens} />
    </div>
  )
}

/** Which job this is, and the way back to the rest of Snagr's work. */
function Breadcrumb({ job }: { job: Job }) {
  return (
    <p className="font-mono text-[12px] tracking-[0.06em] text-ink-3 uppercase">
      <Link to="/activity" className="hover:text-lume">
        Activity
      </Link>{' '}
      / {KIND_NAMES[job.kind]} #{job.id}
    </p>
  )
}

/** What the job did, ahead of what it did it for; nothing for a hunt that
 *  hasn't run or didn't finish. */
function verb(job: Job, isLive: boolean): string | null {
  if (job.kind === 'ground') return 'Market price'
  if (isLive) return 'Hunting'
  if (job.status === 'done') return 'Hunted'
  return null
}

/** The tab title: the heading, as plain text. */
function title(job: Job, isLive: boolean): string {
  const lead = verb(job, isLive)
  if (lead == null) return job.label
  return `${lead} — ${job.kind === 'ground' ? job.item_name : job.label}`
}

/** The heading, with the item linked to its page. */
function Heading({ job, isLive }: { job: Job; isLive: boolean }) {
  if (job.item_id == null) return title(job, isLive)
  const lead = verb(job, isLive)
  return (
    <>
      {lead ? `${lead} — ` : null}
      <Link to={`/items/${job.item_id}`} className="hover:text-lume hover:underline">
        {job.item_name}
      </Link>
      {job.kind === 'hunt' && job.site_name ? ` × ${job.site_name}` : null}
    </>
  )
}

/** Who asked for the job, as the status line says it. Anyone else's is
 *  either another person's work in an admin's view, named by email once the
 *  user list arrives, or a market price someone else watching the item set
 *  going. */
function askedBy(job: Job, me: User | undefined, users: AdminUser[] | undefined): string {
  if (job.user_id === null) return 'system'
  if (job.user_id === me?.id) return 'you'
  return users?.find((user) => user.id === job.user_id)?.email ?? 'another user'
}

function subline(job: Job, isLive: boolean): string {
  const took = job.started_at ? formatDuration(job.started_at, job.finished_at) : 'not started'
  if (isLive) return `${took} · live`
  if (job.status !== 'done') return took
  const { text } = resultText(job)
  const tokens = formatTokens((job.stats?.tokens_in ?? 0) + (job.stats?.tokens_out ?? 0))
  return `${took} · ${text} · ${tokens} tokens`
}
