import { useEffect, useMemo, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { cancelRun, getRun, getRunEvents } from '@/api/endpoints'
import { qk } from '@/api/queries'
import type { RunEvent } from '@/api/types'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Radar } from '@/components/ui/radar'
import { Skeleton } from '@/components/ui/skeleton'
import { TerminalLog, type LogLine } from '@/components/ui/terminal-log'
import { useSession } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { formatDateTime, formatDuration } from '@/lib/time'
import { isRunActive, useRunEvents } from './RunEventsProvider'
import { RunStatusDot } from './RunStatusDot'

function eventLine(event: RunEvent): LogLine {
  return {
    key: `${event.run_id}:${event.seq}`,
    time: new Date(event.ts).toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }),
    level: event.level,
    message: (
      <span className={cn('break-words', event.level === 'error' ? 'text-rise' : undefined)}>
        {event.message}
      </span>
    ),
  }
}

function Stat({ label, value, alert }: { label: string; value: string | number; alert?: boolean }) {
  return (
    <div className="rounded-md border border-hairline bg-surface px-3.5 py-2.5">
      <p className="font-mono text-[10px] tracking-[0.13em] text-ink-3 uppercase">{label}</p>
      <p
        className={cn(
          'mt-1 font-display text-[26px] leading-none font-semibold tnum',
          alert ? 'text-rise' : 'text-ink',
        )}
      >
        {value}
      </p>
    </div>
  )
}

export function RunDetailPage() {
  const { id = '' } = useParams()
  const runId = Number(id)
  const { activeRun, events: liveEvents } = useRunEvents()
  const { data: me } = useSession()
  const queryClient = useQueryClient()
  const logRef = useRef<HTMLDivElement>(null)

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

  // live log follows the tail
  useEffect(() => {
    if (isLive && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [isLive, events])

  const cancelMutation = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['runs'] }),
  })

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
  // owners cancel their own runs; system runs (user_id null) are admin-only
  const canCancel =
    isLive && me != null && (me.role === 'admin' || detail.user_id === me.id)

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-4">
        {isLive ? <Radar size={44} glyph /> : null}
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-2 font-mono text-[10.5px] tracking-[0.14em] text-ink-3 uppercase">
            <RunStatusDot status={detail.status} withLabel />
            <span aria-hidden>·</span>
            <span className="tnum">{formatDateTime(detail.created_at)}</span>
            {detail.user_id === null ? (
              <>
                <span aria-hidden>·</span>
                <span>system</span>
              </>
            ) : null}
          </p>
          <h1
            className={cn(
              'mt-1 font-display text-[26px] leading-tight font-semibold tracking-[0.03em]',
              isLive ? 'text-lume' : 'text-ink',
            )}
          >
            {isLive ? `Sweeping — ${detail.scope_label}` : detail.scope_label}
          </h1>
          <p className="mt-0.5 font-mono text-xs text-ink-3 tnum">
            {detail.started_at ? formatDuration(detail.started_at, detail.finished_at) : 'not started'}
            {isLive ? ' · live' : ''}
          </p>
        </div>
        {canCancel ? (
          <Button size="sm" disabled={cancelMutation.isPending} onClick={() => cancelMutation.mutate()}>
            Cancel
          </Button>
        ) : null}
      </div>

      {detail.error ? (
        <p role="alert" className="rounded-sm border border-rise/40 bg-rise/10 px-3 py-2 text-[13px] text-rise">
          <span aria-hidden>✗</span> {detail.error}
        </p>
      ) : null}

      {detail.stats ? (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Listings checked" value={detail.stats.listings_checked} />
          <Stat label="Prices found" value={detail.stats.prices_found} />
          <Stat label="New listings" value={detail.stats.new_listings} />
          <Stat label="Errors" value={detail.stats.errors} alert={detail.stats.errors > 0} />
        </div>
      ) : null}

      <div
        ref={logRef}
        className="max-h-[32rem] overflow-y-auto rounded-lg border border-hairline bg-well px-4 py-3"
      >
        {events.length === 0 ? (
          <p className="py-2 font-mono text-xs text-ink-3">
            {isLive ? 'Waiting for the agent…' : 'No events were recorded for this run.'}
          </p>
        ) : (
          <TerminalLog lines={events.map(eventLine)} />
        )}
      </div>
    </div>
  )
}
