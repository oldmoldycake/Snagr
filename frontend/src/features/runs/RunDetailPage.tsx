import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { getRun, getRunEvents } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { RunEvent, RunEventLevel } from '@/api/types'
import { Card, CardBody } from '@/components/ui/card'
import { EmptyState } from '@/components/ui/empty-state'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/cn'
import { formatDateTime, formatDuration } from '@/lib/time'
import { isRunActive, useRunEvents } from './RunEventsProvider'
import { RunStatusDot } from './RunStatusDot'

const LEVEL_GLYPHS: Record<RunEventLevel, { glyph: string; className: string }> = {
  info: { glyph: '›', className: 'text-ink-3' },
  success: { glyph: '✓', className: 'text-drop' },
  warn: { glyph: '⚠', className: 'text-warn' },
  error: { glyph: '✗', className: 'text-rise' },
}

function Stat({ label, value, alert }: { label: string; value: string | number; alert?: boolean }) {
  return (
    <div className="rounded-md border border-hairline bg-surface px-3 py-2">
      <p className="text-[11px] tracking-wide text-ink-3 uppercase">{label}</p>
      <p className={cn('mt-0.5 font-mono text-lg font-semibold tnum', alert ? 'text-rise' : 'text-ink')}>
        {value}
      </p>
    </div>
  )
}

export function RunDetailPage() {
  const { id = '' } = useParams()
  const runId = Number(id)
  const { activeRun, events: liveEvents } = useRunEvents()

  const isLive = isRunActive(activeRun) && activeRun?.id === runId

  const run = useQuery({
    queryKey: qk.run(runId),
    queryFn: () => getRun(runId),
    refetchInterval: isLive ? 4000 : false,
  })

  const fetchedEvents = useQuery({
    queryKey: qk.runEvents(runId),
    queryFn: () => getRunEvents(runId),
    enabled: !isLive,
  })

  const events: RunEvent[] = useMemo(() => {
    if (isLive) return liveEvents
    return fetchedEvents.data?.data ?? []
  }, [isLive, liveEvents, fetchedEvents.data])

  if (run.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-48" />
      </div>
    )
  }

  if (!run.data) {
    return <EmptyState title="Run not found" description="It may have been cleaned up." />
  }

  const detail = run.data

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-center gap-2">
          <RunStatusDot status={detail.status} />
          <h1 className="font-display text-lg font-semibold text-ink">{detail.scope_label}</h1>
        </div>
        <p className="mt-1 font-mono text-xs text-ink-3 tnum">
          {formatDateTime(detail.created_at)}
          {detail.started_at ? ` · ${formatDuration(detail.started_at, detail.finished_at)}` : ''}
          {isLive ? ' · live' : ''}
        </p>
        {detail.error ? <p className="mt-2 text-[13px] text-rise">{detail.error}</p> : null}
      </div>

      {detail.stats ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Listings checked" value={detail.stats.listings_checked} />
          <Stat label="Prices found" value={detail.stats.prices_found} />
          <Stat label="New listings" value={detail.stats.new_listings} />
          <Stat label="Errors" value={detail.stats.errors} alert={detail.stats.errors > 0} />
        </div>
      ) : null}

      <Card>
        <CardBody className="px-0 py-2">
          {events.length === 0 ? (
            <p className="px-4 py-4 font-mono text-xs text-ink-3">
              {isLive ? 'Waiting for the agent…' : 'No events were recorded for this run.'}
            </p>
          ) : (
            <div className="max-h-[32rem] overflow-y-auto">
              {events.map((event) => {
                const { glyph, className } = LEVEL_GLYPHS[event.level]
                return (
                  <div key={`${event.run_id}:${event.seq}`} className="flex gap-2 px-4 py-1 font-mono text-xs leading-5">
                    <span className="shrink-0 text-ink-3/60 tnum">
                      {new Date(event.ts).toLocaleTimeString('en-US', {
                        hour12: false,
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                    <span aria-hidden className={cn('shrink-0', className)}>
                      {glyph}
                    </span>
                    <span className={cn('break-words', event.level === 'error' ? 'text-rise' : 'text-ink-2')}>
                      {event.message}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}
