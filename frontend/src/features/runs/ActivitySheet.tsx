import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowDown, ExternalLink } from 'lucide-react'
import { cancelRun } from '@/api/endpoints'
import type { RunEvent } from '@/api/types'
import { Radar } from '@/components/ui/radar'
import { Sheet, SheetContent, SheetDescription, SheetTitle } from '@/components/ui/sheet'
import { TerminalLogLine } from '@/components/ui/terminal-log'
import { useSession } from '@/features/auth/useSession'
import { cn } from '@/lib/cn'
import { formatDuration } from '@/lib/time'
import { isRunActive, useRunEvents } from './RunEventsProvider'
import { RunStatusDot } from './RunStatusDot'

function EventLine({ event }: { event: RunEvent }) {
  return (
    <div className="px-4 py-0.5">
      <TerminalLogLine
        line={{
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
        }}
      />
    </div>
  )
}

function ElapsedTimer({ startedAt }: { startedAt: string | null }) {
  const [, force] = useState(0)
  useEffect(() => {
    const t = setInterval(() => force((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [])
  return <span className="font-mono text-xs text-ink-3 tnum">{formatDuration(startedAt)}</span>
}

export function ActivitySheet() {
  const { activeRun, events, connection, panelOpen, setPanelOpen } = useRunEvents()
  const { data: me } = useSession()
  const queryClient = useQueryClient()
  const logRef = useRef<HTMLDivElement>(null)
  const [following, setFollowing] = useState(true)

  const active = isRunActive(activeRun)
  // owners cancel their own runs; system runs (user_id null) are admin-only
  const canCancel = me != null && (me.role === 'admin' || activeRun?.user_id === me.id)

  const cancelMutation = useMutation({
    mutationFn: (id: number) => cancelRun(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['runs'] }),
  })

  useEffect(() => {
    if (following && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [events, following])

  const onScroll = () => {
    const el = logRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40
    setFollowing(atBottom)
  }

  return (
    <Sheet open={panelOpen} onOpenChange={setPanelOpen}>
      <SheetContent aria-describedby={undefined}>
        <div className="border-b border-hairline px-4 py-3">
          <div className="flex items-center gap-2.5 pr-8">
            {active ? (
              <Radar size={22} />
            ) : activeRun ? (
              <RunStatusDot status={activeRun.status} />
            ) : (
              <Radar size={22} animate={false} />
            )}
            <SheetTitle className="min-w-0 truncate font-display text-[15px] font-semibold tracking-[0.06em] text-ink uppercase">
              {activeRun ? activeRun.scope_label : 'Agent activity'}
            </SheetTitle>
            {active && activeRun ? <ElapsedTimer startedAt={activeRun.started_at} /> : null}
          </div>
          <SheetDescription className="mt-1 flex flex-wrap items-center gap-3 text-xs text-ink-3">
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn(
                  'size-1.5 rounded-full',
                  connection === 'live' ? 'bg-drop' : 'animate-pulse bg-warn',
                )}
              />
              {connection === 'live' ? 'live' : 'reconnecting…'}
            </span>
            {activeRun ? (
              <Link
                to={`/runs/${activeRun.id}`}
                onClick={() => setPanelOpen(false)}
                className="flex items-center gap-1 text-ink-3 hover:text-ink"
              >
                Open run page <ExternalLink className="size-3" />
              </Link>
            ) : null}
            {active && activeRun && canCancel ? (
              <button
                type="button"
                className="text-rise hover:underline disabled:opacity-50"
                disabled={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate(activeRun.id)}
              >
                Cancel run
              </button>
            ) : null}
          </SheetDescription>
        </div>

        <div ref={logRef} onScroll={onScroll} className="relative flex-1 overflow-y-auto bg-well py-2">
          {events.length === 0 ? (
            <p className="px-4 py-6 font-mono text-xs text-ink-3">
              {active ? 'Waiting for the agent…' : 'No run activity yet. Start a run to watch it live.'}
            </p>
          ) : (
            events.map((event) => <EventLine key={`${event.run_id}:${event.seq}`} event={event} />)
          )}
        </div>

        {!following ? (
          <button
            type="button"
            onClick={() => {
              setFollowing(true)
              logRef.current?.scrollTo({ top: logRef.current.scrollHeight })
            }}
            className="absolute right-4 bottom-[max(1rem,env(safe-area-inset-bottom))] flex items-center gap-1 rounded-full border border-hairline bg-overlay px-2.5 py-2 text-xs text-ink-2 shadow-lg hover:text-ink"
          >
            <ArrowDown className="size-3" /> Follow
          </button>
        ) : null}
      </SheetContent>
    </Sheet>
  )
}
