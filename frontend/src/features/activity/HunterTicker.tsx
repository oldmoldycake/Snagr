import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getJobsSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { Radar } from '@/components/ui/radar'
import { LogGlyph } from '@/components/ui/terminal-log'
import { useInstance } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { formatDuration, formatInterval, relativeTime } from '@/lib/time'
import { checkLine, glyphFor, resultText } from './lines'
import { useJobs } from './JobsProvider'
import { behindSchedule, nextCheckText } from './timeline'

const SUMMARY_POLL_MS = 30_000

/** Ticking elapsed for the live hunt; re-renders once a second. */
function useElapsed(startedAt: string | null | undefined, running: boolean): string {
  const [, setTick] = useState(0)
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setTick((t) => t + 1), 1000)
    return () => clearInterval(id)
  }, [running])
  if (!running || !startedAt) return ''
  return formatDuration(startedAt)
}

/**
 * Beat two of the dashboard: the hunter's presence as a single strip. It says
 * what is happening and what is next, never what was found — counts belong to
 * the pulse line above it (the dashboard's "once only" rule).
 *
 * On a phone the message gets a line of its own and only its most important
 * part: squeezed beside the label, it would be cut to a few characters.
 */
export function HunterTicker({ className }: { className?: string }) {
  const { live, events, checks, setPanelOpen } = useJobs()
  const summary = useQuery({
    queryKey: qk.jobsSummary,
    queryFn: getJobsSummary,
    refetchInterval: SUMMARY_POLL_MS,
  })

  const instance = useInstance().data
  const huntingOff = instance?.hunt_enabled === false
  const hunts = live.filter((job) => job.kind === 'hunt')
  const hunt = hunts.at(0)
  const elapsed = useElapsed(hunt?.started_at, hunt != null)
  const checksRunning = summary.data?.checks_running ?? 0

  const barClass = cn(
    'flex h-11 w-full items-center gap-3 rounded-md border border-hairline bg-well px-4 text-left font-mono text-[12px]',
    'max-sm:h-auto max-sm:flex-wrap max-sm:gap-y-1 max-sm:py-2',
    className,
  )
  const labelClass = 'shrink-0 tracking-[0.12em] uppercase max-sm:min-w-0 max-sm:flex-1 max-sm:truncate'
  const messageClass = 'min-w-0 flex-1 truncate text-ink-2 max-sm:order-last max-sm:basis-full max-sm:pl-9'

  if (hunt) {
    const latest = (events.get(hunt.id) ?? []).at(-1)
    const level = latest ? glyphFor(latest) : null
    return (
      <button
        type="button"
        onClick={() => setPanelOpen(true)}
        className={cn(barClass, 'hover:border-hairline-strong')}
      >
        <Radar size={24} />
        <span className={cn(labelClass, 'text-lume')}>
          Hunting · {live.length} running
          {checksRunning > 0 ? <span className="max-sm:hidden"> · {checksRunning} price checks</span> : null}
        </span>
        <span aria-hidden className="shrink-0 text-ink-3 max-sm:hidden">
          │
        </span>
        <span className={messageClass}>
          {latest && level ? (
            <>
              <LogGlyph level={level} />{' '}
              {latest.message}
            </>
          ) : (
            'Starting up…'
          )}
        </span>
        {elapsed ? <span className="shrink-0 text-ink-3 tnum max-sm:hidden">{elapsed}</span> : null}
        <span className="shrink-0 tracking-[0.08em] text-ink-2">View ↗</span>
      </button>
    )
  }

  const lastCheck = checks.at(-1)
  // overdue work with nothing running contradicts "Idle", and outranks
  // "Hunting off": checks are still meant to run then
  const behind = summary.data != null && behindSchedule(summary.data, !huntingOff)
  let label = 'Idle'
  if (checksRunning > 0) label = `Checking ${checksRunning} ${checksRunning === 1 ? 'price' : 'prices'}`
  else if (behind) label = 'Behind schedule'
  else if (huntingOff) label = 'Hunting off'
  return (
    <div className={barClass}>
      <Radar size={24} animate={checksRunning > 0} />
      <span
        className={cn(labelClass, checksRunning > 0 ? 'text-lume' : behind ? 'text-warn' : 'text-ink-3')}
      >
        {label}
      </span>
      <span aria-hidden className="shrink-0 text-ink-3 max-sm:hidden">
        │
      </span>
      <span className={messageClass}>
        {checksRunning > 0 && lastCheck ? (
          <TickerCheck check={lastCheck} />
        ) : huntingOff && !behind ? (
          <>
            <span className="max-sm:hidden">off on this server · </span>
            prices are still checked every {formatInterval(instance.recheck_interval_default)}
          </>
        ) : (
          <IdleMessage summary={summary.data} pending={summary.isPending} />
        )}
      </span>
      <Link to="/activity" className="shrink-0 tracking-[0.08em] text-ink-2 hover:text-lume">
        Activity →
      </Link>
    </div>
  )
}

function TickerCheck({ check }: { check: Parameters<typeof checkLine>[0] }) {
  const line = checkLine(check, 0)
  return (
    <>
      <LogGlyph level={line.level} />{' '}
      {line.message}
    </>
  )
}

function IdleMessage({
  summary,
  pending,
}: {
  summary: ReturnType<typeof getJobsSummary> extends Promise<infer T> ? T | undefined : never
  pending: boolean
}) {
  // Pending is not "nothing yet" — stay blank until the query answers, so the
  // empty-state copy can't flash on load.
  if (pending || summary == null) return null
  if (summary.listings_watched === 0 && summary.last_hunt == null) {
    return <>Add an item and Snagr starts looking for it.</>
  }
  // most important first: a phone shows only the first part
  const paused = summary.paused_sites[0]
  const parts: ReactNode[] = []
  if (paused) {
    parts.push(
      <>
        <span aria-hidden className="text-warn">
          ⚠
        </span>{' '}
        {paused.site_name} paused
      </>,
    )
  }
  if (summary.next_check_at) parts.push(nextCheckText(summary.next_check_at))
  if (summary.last_hunt?.finished_at) {
    parts.push(
      `last hunt ${relativeTime(summary.last_hunt.finished_at)}, ${resultText(summary.last_hunt).text.replace(/^✚ /, '')}`,
    )
  }
  return (
    <>
      {parts[0]}
      {parts.slice(1).map((part, i) => (
        <span key={i} className="max-sm:hidden"> · {part}</span>
      ))}
    </>
  )
}
