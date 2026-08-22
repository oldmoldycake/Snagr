import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { listRuns } from '@/api/endpoints'
import { qk } from '@/api/queries'
import { Radar } from '@/components/ui/radar'
import { LOG_GLYPHS } from '@/components/ui/terminal-log'
import { cn } from '@/lib/cn'
import { formatDuration, relativeTime } from '@/lib/time'
import { isRunActive, useRunEvents } from './RunEventsProvider'

/** Ticking m/s elapsed for the live run; re-renders once a second. */
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
 * Beat two of the dashboard: the agent's presence as a single live strip.
 * Sweeping — radar spins, the latest event ticks through; idle — the last
 * sweep's outcome. Click opens the activity panel.
 */
export function AgentTicker({ className }: { className?: string }) {
  const { activeRun, events, setPanelOpen } = useRunEvents()
  const active = isRunActive(activeRun)
  const elapsed = useElapsed(activeRun?.started_at, active)

  const lastRun = useQuery({
    queryKey: qk.runs({ per_page: 1 }),
    queryFn: () => listRuns({ per_page: 1 }),
    enabled: !active,
  })

  const barClass = cn(
    'flex h-11 w-full items-center gap-3 rounded-md border border-hairline bg-well px-4 text-left font-mono text-[11.5px]',
    className,
  )

  if (active) {
    const latest = events[events.length - 1]
    const level = latest ? LOG_GLYPHS[latest.level] : null
    return (
      <button type="button" onClick={() => setPanelOpen(true)} className={cn(barClass, 'hover:border-hairline-strong')}>
        <Radar size={24} />
        <span className="shrink-0 tracking-[0.12em] text-lume uppercase">
          Sweeping · {activeRun?.scope_label}
        </span>
        <span aria-hidden className="shrink-0 text-ink-3">
          │
        </span>
        <span className="min-w-0 flex-1 truncate text-ink-2">
          {latest ? (
            <>
              <span aria-hidden className={level!.className}>
                {level!.glyph}
              </span>{' '}
              {latest.message}
            </>
          ) : (
            'Starting up…'
          )}
        </span>
        {elapsed ? <span className="shrink-0 text-ink-3 tnum">{elapsed}</span> : null}
        <span className="shrink-0 tracking-[0.08em] text-ink-2">WATCH ↗</span>
      </button>
    )
  }

  const last = lastRun.data?.data[0]
  return (
    <div className={barClass}>
      <Radar size={24} animate={false} />
      <span className="shrink-0 tracking-[0.12em] text-ink-3 uppercase">Agent idle</span>
      <span aria-hidden className="shrink-0 text-ink-3">
        │
      </span>
      <span className="min-w-0 flex-1 truncate text-ink-2">
        {last == null ? (
          'No sweeps yet — run the agent to get eyes on your targets.'
        ) : last.status === 'failed' ? (
          <>
            <span aria-hidden className="text-rise">
              ✗
            </span>{' '}
            {last.scope_label} failed {relativeTime(last.finished_at)}
            {last.error ? ` — ${last.error}` : ''}
          </>
        ) : (
          <>
            <span aria-hidden className="text-drop">
              ✓
            </span>{' '}
            {last.scope_label} — {relativeTime(last.finished_at)}
            {last.stats
              ? ` · ${last.stats.listings_checked} checked · ${last.stats.new_listings} new`
              : ''}
          </>
        )}
      </span>
      <Link to="/runs" className="shrink-0 tracking-[0.08em] text-ink-2 hover:text-lume">
        ALL RUNS →
      </Link>
    </div>
  )
}
