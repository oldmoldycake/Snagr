import { useState, type ReactNode } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { listJobs } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { Job, JobListParams, JobsSummary } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { ErrorState } from '@/components/ui/error-state'
import { Pagination } from '@/components/ui/pagination'
import { Segmented } from '@/components/ui/segmented'
import { Skeleton } from '@/components/ui/skeleton'
import { useInstance, useSession } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { priceMethodLabel } from '@/lib/priceMethod'
import { clockTime, countdown, formatMillis, formatTokens } from '@/lib/time'
import { CheckPricesButton } from './CheckPricesButton'
import { ChecksTail } from './ChecksTail'
import { JobStatusDot } from './JobStatusDot'
import { LiveHuntRow } from './LiveHunts'
import { reasonText, resultText, waitingForSite } from './lines'
import { useJobs } from './JobsProvider'
import {
  checksDue,
  foldQueue,
  groupByHour,
  queuedWait,
  rowTime,
  type DueState,
  type QueuedWait,
} from './timeline'
import { useTick } from './useTick'

type Filter = 'hunt' | 'ground' | 'recheck' | 'failed' | 'all'

const FILTERS: readonly { value: Filter; label: string }[] = [
  { value: 'hunt', label: 'Hunts' },
  { value: 'ground', label: 'Market price' },
  { value: 'recheck', label: 'Checks' },
  { value: 'failed', label: 'Failed' },
  { value: 'all', label: 'All' },
]

const REMEMBERED = 'snagr:activity-filter'
/** How a recheck fetched the page, for its expanded detail line. */
const TRANSPORT_LABELS: Record<string, string> = {
  static: 'plain download',
  browser: 'in a browser',
}
const FINISHED = 'done,failed,cancelled'
const PENDING = {
  status: 'pending',
  kind: 'hunt,ground',
  per_page: 8,
} as const

// The remembered filter is a per-browser convenience, so storage failures
// (private mode, blocked site data, a full quota) are ignored rather than
// surfaced: the page falls back to Hunts.

/** The filter this browser last chose, or Hunts. */
function rememberedFilter(): Filter {
  try {
    const held = localStorage.getItem(REMEMBERED)
    return FILTERS.find((f) => f.value === held)?.value ?? 'hunt'
  } catch {
    return 'hunt'
  }
}

function rememberFilter(filter: Filter) {
  try {
    localStorage.setItem(REMEMBERED, filter)
  } catch {
    // see rememberedFilter()
  }
}

function historyParams(filter: Filter, page: number): JobListParams {
  if (filter === 'failed') return { status: 'failed', page }
  if (filter === 'all') return { status: FINISHED, page }
  return { status: FINISHED, kind: filter, page }
}

/**
 * The hunter's work on one clock: what is queued above the "now" line, what
 * is running on it, and what finished below it, so there is one place to look
 * for any job whatever its state. The queue reads like a to-do list, soonest
 * first and folded after the next few so it never buries "now" on a phone;
 * the finished work reads back in time, newest first and headed by the hour.
 *
 * The filter narrows only the finished part — the queue and the live work
 * are always shown, because they are what "now" means. Hunts are the default
 * because they are the decisions; Checks exists to debug one site and is
 * never where you land, because 2,400 rows a day would bury everything else.
 */
export function Timeline({ summary }: { summary?: JobsSummary }) {
  const [filter, setFilter] = useState<Filter>(rememberedFilter)
  const [page, setPage] = useState(1)
  const [queueOpen, setQueueOpen] = useState(false)

  const queued = useQuery({
    queryKey: qk.jobs(PENDING),
    queryFn: () => listJobs(PENDING),
  })
  const params = historyParams(filter, page)
  const history = useQuery({
    queryKey: qk.jobs(params),
    queryFn: () => listJobs(params),
    placeholderData: keepPreviousData,
  })

  const { live } = useJobs()
  const huntEnabled = useInstance().data?.hunt_enabled !== false
  const nothingAtAll =
    summary != null &&
    summary.listings_watched === 0 &&
    summary.last_hunt == null &&
    live.length === 0 &&
    queued.isSuccess &&
    queued.data.data.length === 0
  if (nothingAtAll) {
    return (
      <EmptyState
        title="Nothing has happened yet"
        description="Add an item and Snagr starts looking. Its prices are checked automatically from then on."
      />
    )
  }

  const queue = (queued.data?.data ?? []).map((job) => ({
    job,
    wait: queuedWait(job, {
      pausedSites: summary?.paused_sites ?? [],
      huntEnabled,
      running: live.some((running) => running.kind === job.kind),
    }),
  }))
  const checksWait = checksDue(summary)
  const late = checksWait === 'overdue' || queue.some(({ wait }) => wait.state === 'overdue')
  const upcoming = foldQueue(queue, queueOpen)
  const groups = groupByHour(history.data?.data ?? [])

  return (
    <section aria-label="Timeline" className="relative">
      <span aria-hidden className="absolute inset-y-0 left-[calc(5.125rem_-_1px)] w-0.5 bg-grid" />
      <ol className="relative space-y-0.5">
        <Heading label="Next" />
        {queued.isError ? (
          <Row>
            <ErrorState
              className="py-6"
              title="Couldn't load the queue"
              error={queued.error}
              onRetry={() => void queued.refetch()}
              retrying={queued.isFetching}
            />
          </Row>
        ) : (
          <>
            {upcoming.shown.map(({ job, wait }) => (
              <QueuedRow key={job.id} job={job} wait={wait} />
            ))}
            {upcoming.folded > 0 ? (
              <Row>
                <Button
                  variant="ghost"
                  size="sm"
                  aria-expanded={queueOpen}
                  onClick={() => setQueueOpen((v) => !v)}
                  className="-ml-2"
                >
                  {queueOpen ? 'Show fewer' : `Show ${upcoming.folded} more`}
                </Button>
              </Row>
            ) : null}
          </>
        )}
        <QueuedChecks summary={summary} wait={checksWait} />

        <NowBlock summary={summary} late={late} />

        <Heading label="Earlier">
          <Segmented
            ariaLabel="What to show"
            options={FILTERS}
            value={filter}
            onChange={(value) => {
              setFilter(value)
              setPage(1)
              rememberFilter(value)
            }}
          />
        </Heading>
        {history.isLoading ? (
          <Row>
            <div className="space-y-2 py-2">
              <Skeleton className="h-6" />
              <Skeleton className="h-6" />
            </div>
          </Row>
        ) : history.isError ? (
          <Row>
            <ErrorState
              className="py-6"
              title="Couldn't load the history"
              error={history.error}
              onRetry={() => void history.refetch()}
              retrying={history.isFetching}
            />
          </Row>
        ) : groups.length === 0 ? (
          <Row>
            <p className="py-2 font-mono text-[12px] text-ink-3">
              {filter === 'failed' ? 'Nothing has failed.' : 'Nothing has finished yet.'}
            </p>
          </Row>
        ) : (
          groups.map((group) => (
            <HourGroupRows key={group.key} label={group.label} jobs={group.jobs} />
          ))
        )}
      </ol>
      {history.data && history.data.meta.total > history.data.meta.per_page ? (
        <div className="mt-4 flex justify-end">
          <Pagination meta={history.data.meta} onPage={setPage} />
        </div>
      ) : null}
    </section>
  )
}

/** Every row lines up on the rail: a time, a marker on the line, the content. */
function Row({
  time,
  marker,
  children,
  className,
}: {
  time?: ReactNode
  marker?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <li
      className={cn('grid grid-cols-[4rem_0.75rem_minmax(0,1fr)] items-center gap-x-3', className)}
    >
      <span className="text-right font-mono text-[12px] whitespace-nowrap text-ink-3 tnum">
        {time}
      </span>
      <span className="grid h-5 place-items-center bg-page">{marker}</span>
      <div className="min-w-0">{children}</div>
    </li>
  )
}

function Heading({ label, children }: { label: string; children?: ReactNode }) {
  return (
    <li className="grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-x-3 pt-5 pb-2 first:pt-0">
      <h2 className="text-right font-mono text-[12px] text-ink-3">
        {label}
      </h2>
      <div className="flex min-h-7 flex-wrap items-center gap-3 border-b border-hairline pb-1.5 pl-[calc(0.75rem_+_0.75rem)]">
        {children}
      </div>
    </li>
  )
}

function Who({ job }: { job: Job }) {
  return (
    <>
      <span className="font-medium text-ink">{job.item_name}</span>
      {job.kind === 'ground' ? (
        <span className="text-ink-3"> · market price</span>
      ) : job.kind === 'recheck' ? (
        <span className="text-ink-3"> · check</span>
      ) : job.site_name ? (
        <span className="text-ink-3"> × {job.site_name}</span>
      ) : null}
      {job.user_id === null ? (
        <span className="ml-2 font-mono text-[12px] text-ink-3">system</span>
      ) : null}
    </>
  )
}

function QueuedRow({ job, wait }: { job: Job; wait: QueuedWait }) {
  const blocked = wait.state === 'site-paused'
  return (
    <Row
      time={queuedTime(job, wait)}
      marker={
        blocked ? (
          <span aria-hidden className="font-mono text-xs text-warn">
            ⚠
          </span>
        ) : (
          <JobStatusDot status="pending" />
        )
      }
      className="py-1.5"
    >
      <p className="flex flex-wrap items-baseline gap-x-2 text-[14px]">
        <span className={cn(blocked && 'ink-muted')}>
          <Who job={job} />
        </span>
        <span
          className={cn(
            'font-mono text-[12px]',
            blocked ? 'rounded-sm bg-warn/10 px-1.5 py-0.5 text-warn' : 'text-ink-3',
          )}
        >
          {job.kind === 'ground' ? '' : 'hunt · '}
          {queuedText(job, wait)}
        </span>
      </p>
    </Row>
  )
}

/** A queued row's time: when it runs, or where it stands once that has passed. */
function queuedTime(job: Job, wait: QueuedWait): string {
  switch (wait.state) {
    case 'site-paused':
      return clockTime(wait.until)
    case 'hunting-off':
      return 'on hold'
    case 'in-line':
      return 'in line'
    default:
      return countdown(job.run_after)
  }
}

/** Why it was queued, and what holds it when that isn't the hunter's own schedule. */
function queuedText(job: Job, wait: QueuedWait): string {
  if (wait.state === 'hunting-off') return 'hunting is off on this server'
  if (wait.state === 'site-paused' && job.reason !== 'paused') {
    return `${reasonText(job)} · ${waitingForSite(job)}`
  }
  return reasonText(job)
}

/** Forty-four checks are a cadence, not a list: one row, and the lever to pull them all in. */
function QueuedChecks({ summary, wait }: { summary?: JobsSummary; wait: DueState }) {
  const pending = summary?.checks_pending ?? 0
  return (
    <Row
      time={
        pending > 0 ? (wait === 'in-line' ? 'in line' : countdown(summary?.next_check_at)) : null
      }
      marker={<JobStatusDot status="pending" />}
      className="py-1.5"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <p className="min-w-0 flex-1 font-mono text-[12px] text-ink-3">
          {pending > 0 ? (
            <>
              <span className="text-ink">{pending} price checks</span>{' '}
              {wait === 'scheduled' ? 'spread over the coming half hour' : 'waiting'}
            </>
          ) : (
            'No price checks queued'
          )}
        </p>
        <CheckPricesButton scope="global" label="Check all prices" size="sm" />
      </div>
    </Row>
  )
}

function NowBlock({ summary, late }: { summary?: JobsSummary; late: boolean }) {
  const { live } = useJobs()
  const isAdmin = useSession().data?.role === 'admin'
  const huntEnabled = useInstance().data?.hunt_enabled !== false
  useTick(true)
  const busy = live.length > 0 || (summary?.checks_running ?? 0) > 0
  const now = new Date().toISOString()

  return (
    <>
      <li className="grid grid-cols-[4rem_0.75rem_minmax(0,1fr)] items-center gap-x-3 pt-4 pb-1">
        <span
          className={cn(
            'text-right font-mono text-[12px] font-semibold tracking-[0.08em] uppercase',
            busy ? 'text-lume' : 'text-ink-2',
          )}
        >
          Now
        </span>
        <span className="grid h-5 place-items-center bg-page">
          <span
            aria-hidden
            className={cn(
              'size-3 rounded-full',
              busy ? 'animate-pulse bg-lume shadow-[0_0_0_5px_var(--color-lume-glow)]' : 'bg-ink-3',
            )}
          />
        </span>
        <div className="flex items-center gap-3">
          <span
            aria-hidden
            className={cn(
              'h-px flex-1',
              busy ? 'bg-gradient-to-r from-lume to-transparent' : 'bg-hairline-strong',
            )}
          />
          <span className="font-mono text-[12px] text-ink-3 tnum">{clockTime(now)}</span>
        </div>
      </li>
      <li className="relative grid grid-cols-[4rem_0.75rem_minmax(0,1fr)] gap-x-3 pt-2 pb-3">
        {busy ? (
          <span
            aria-hidden
            className="absolute inset-y-0 left-[calc(5.125rem_-_1px)] w-0.5 bg-lume"
          />
        ) : null}
        <span />
        <span />
        <div className="min-w-0 space-y-2.5">
          {live.map((job) => (
            <div key={job.id} className="rounded-lg border border-lume/30 bg-raised">
              <LiveHuntRow job={job} />
            </div>
          ))}
          <ChecksTail summary={summary} />
          {late ? (
            <p className="font-mono text-[12px] text-warn">
              <span aria-hidden>⚠</span>{' '}
              {isAdmin
                ? "Overdue work hasn't started: Snagr may be stopped or waiting out an error. Its log says which."
                : "Overdue work hasn't started: Snagr may be busy with other people's work, waiting out an error, or stopped."}
            </p>
          ) : !busy ? (
            <p className="font-mono text-[12px] text-ink-3">
              Idle
              {huntEnabled && summary?.next_hunt_at
                ? ` — next hunt ${nextHunt(summary.next_hunt_at)}`
                : null}
            </p>
          ) : null}
        </div>
      </li>
    </>
  )
}

/** `countdown` says "now" once a job is due; "next hunt now" reads as a command. */
function nextHunt(iso: string): string {
  const left = countdown(iso)
  return left === 'now' ? 'due now' : left
}

function HourGroupRows({ label, jobs }: { label: string; jobs: Job[] }) {
  return (
    <>
      <li className="grid grid-cols-[4rem_minmax(0,1fr)] items-center gap-x-3 pt-4 pb-1">
        <span className="text-right font-mono text-[12px] whitespace-nowrap text-ink-3">
          {label}
        </span>
        <span aria-hidden className="ml-[calc(0.75rem_+_0.75rem)] h-px bg-hairline" />
      </li>
      {jobs.map((job) => (
        <PastRow key={job.id} job={job} />
      ))}
    </>
  )
}

function PastRow({ job }: { job: Job }) {
  const [open, setOpen] = useState(false)
  const result = resultText(job)
  const found = job.status === 'done' && (job.stats?.new_listings ?? 0) > 0
  const took = formatMillis(job.stats?.duration_ms)
  const tokens = formatTokens((job.stats?.tokens_in ?? 0) + (job.stats?.tokens_out ?? 0))

  const body = (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2 pr-2">
      <p className="min-w-0 flex-1 basis-48 truncate text-[14px]">
        <Who job={job} />
      </p>
      <p className={cn('font-mono text-xs tnum sm:min-w-44', result.tone)}>{result.text}</p>
      <p className="hidden min-w-24 text-right font-mono text-[12px] whitespace-nowrap text-ink-3 sm:block tnum">
        {took} · {tokens}
      </p>
    </div>
  )

  if (job.kind === 'recheck') {
    return (
      <>
        <Row
          time={rowTime(job.finished_at ?? job.created_at)}
          marker={<JobStatusDot status={job.status} />}
        >
          <button
            type="button"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
            className="block w-full rounded-md text-left hover:bg-raised"
          >
            {body}
          </button>
        </Row>
        {open ? (
          <Row>
            <p className="pb-2 font-mono text-[12px] text-ink-3">
              {[
                job.stats?.method === 'llm' ? 'read by AI' : priceMethodLabel(job.stats?.method),
                TRANSPORT_LABELS[job.stats?.transport ?? ''],
                took,
                job.error,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>
          </Row>
        ) : null}
      </>
    )
  }

  return (
    <Row
      time={rowTime(job.finished_at ?? job.created_at)}
      marker={<JobStatusDot status={job.status} />}
    >
      <Link
        to={`/activity/${job.id}`}
        className={cn('block rounded-md pl-2 -ml-2 hover:bg-raised', found && 'bg-lume-glow/40')}
      >
        {body}
      </Link>
    </Row>
  )
}
