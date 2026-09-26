import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { getJobsSummary } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { Radar } from '@/components/ui/radar'
import { useInstance } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { countdown, formatDuration, formatInterval, relativeTime } from '@/lib/time'
import { GLYPHS, checkLine, glyphFor, resultText } from './lines'
import { useJobs } from './JobsProvider'

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
  const hunt = live.find((job) => job.kind === 'hunt')
  const elapsed = useElapsed(hunt?.started_at, hunt != null)
  const checksRunning = summary.data?.checks_running ?? 0

  const barClass = cn(
    'flex h-11 w-full items-center gap-3 rounded-md border border-hairline bg-well px-4 text-left font-mono text-[11.5px]',
    className,
  )

  if (hunt) {
    const latest = (events.get(hunt.id) ?? []).at(-1)
    const glyph = latest ? GLYPHS[glyphFor(latest)] : null
    return (
      <button
        type="button"
        onClick={() => setPanelOpen(true)}
        className={cn(barClass, 'hover:border-hairline-strong')}
      >
        <Radar size={24} />
        <span className="shrink-0 tracking-[0.12em] text-lume uppercase">
          Hunting · {live.length} running
          {checksRunning > 0 ? ` · ${checksRunning} price checks` : ''}
        </span>
        <span aria-hidden className="shrink-0 text-ink-3">
          │
        </span>
        <span className="min-w-0 flex-1 truncate text-ink-2">
          {latest && glyph ? (
            <>
              <span aria-hidden className={glyph.className}>
                {glyph.glyph}
              </span>{' '}
              {latest.message}
            </>
          ) : (
            'Starting up…'
          )}
        </span>
        {elapsed ? <span className="shrink-0 text-ink-3 tnum">{elapsed}</span> : null}
        <span className="shrink-0 tracking-[0.08em] text-ink-2">View ↗</span>
      </button>
    )
  }

  const lastCheck = checks.at(-1)
  return (
    <div className={barClass}>
      <Radar size={24} animate={checksRunning > 0} />
      <span
        className={cn(
          'shrink-0 tracking-[0.12em] uppercase',
          checksRunning > 0 ? 'text-lume' : 'text-ink-3',
        )}
      >
        {checksRunning > 0 ? `Checking ${checksRunning} ${checksRunning === 1 ? 'price' : 'prices'}` : huntingOff ? 'Hunting off' : 'Idle'}
      </span>
      <span aria-hidden className="shrink-0 text-ink-3">
        │
      </span>
      <span className="min-w-0 flex-1 truncate text-ink-2">
        {checksRunning > 0 && lastCheck ? (
          <TickerCheck check={lastCheck} />
        ) : huntingOff ? (
          <>
            off on this server · prices are still checked every{' '}
            {formatInterval(instance.recheck_interval_default)}
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
  const glyph = GLYPHS[line.level]
  return (
    <>
      <span aria-hidden className={glyph.className}>
        {glyph.glyph}
      </span>{' '}
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
  const paused = summary.paused_sites[0]
  const parts: string[] = []
  if (summary.next_check_at) parts.push(`next check ${countdown(summary.next_check_at)}`)
  if (summary.last_hunt?.finished_at) {
    parts.push(
      `last hunt ${relativeTime(summary.last_hunt.finished_at)}, ${resultText(summary.last_hunt).text.replace(/^✚ /, '')}`,
    )
  }
  return (
    <>
      {paused ? (
        <>
          <span aria-hidden className="text-warn">
            ⚠
          </span>{' '}
          {paused.site_name} paused ·{' '}
        </>
      ) : null}
      {parts.join(' · ')}
    </>
  )
}
