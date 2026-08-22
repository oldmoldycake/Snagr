/**
 * One EventSource per session, shared app-wide. Feeds the activity slide-over,
 * the top-bar status pill, and query invalidation when runs finish.
 *
 * Reconnect contract: the server sends `run.snapshot` on every (re)connect; we
 * refetch GET /api/runs/:id/events?after_seq=<highest seq held> and merge by
 * seq — the filtered response is authoritative. The stream is per-viewer, so a
 * filtered viewer legitimately holds a sparse subset of seqs; never infer
 * missed events from seq arithmetic (snapshot last_seq is the run's GLOBAL
 * write cursor).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { getRunEvents, triggerRun } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type { AgentRun, RunCreateRequest, RunEvent, RunSnapshotData } from '@/api/types'

type Connection = 'live' | 'reconnecting'

interface RunEventsContextValue {
  activeRun: AgentRun | null
  /** events for the active (or most recently finished) run, seq-ordered */
  events: RunEvent[]
  connection: Connection
  panelOpen: boolean
  setPanelOpen: (open: boolean) => void
  trigger: (req: RunCreateRequest) => void
  isTriggering: boolean
}

const RunEventsContext = createContext<RunEventsContextValue | null>(null)

export function useRunEvents(): RunEventsContextValue {
  const ctx = useContext(RunEventsContext)
  if (!ctx) throw new Error('useRunEvents must be used inside RunEventsProvider')
  return ctx
}

export function RunEventsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null)
  const [events, setEvents] = useState<RunEvent[]>([])
  const [connection, setConnection] = useState<Connection>('live')
  const [panelOpen, setPanelOpen] = useState(false)
  const lastSeqRef = useRef(0)
  const runIdRef = useRef<number | null>(null)

  const appendEvents = useCallback((incoming: RunEvent[]) => {
    if (incoming.length === 0) return
    setEvents((prev) => {
      const seen = new Set(prev.map((e) => e.seq))
      const fresh = incoming.filter((e) => e.run_id === runIdRef.current && !seen.has(e.seq))
      if (fresh.length === 0) return prev
      const merged = [...prev, ...fresh].sort((a, b) => a.seq - b.seq)
      lastSeqRef.current = merged[merged.length - 1]?.seq ?? lastSeqRef.current
      return merged
    })
  }, [])

  const switchToRun = useCallback((runId: number) => {
    if (runIdRef.current !== runId) {
      runIdRef.current = runId
      lastSeqRef.current = 0
      setEvents([])
    }
  }, [])

  const invalidateAfterRun = useCallback(() => {
    // Cheap and safe: a finished run may have touched prices anywhere in scope.
    void queryClient.invalidateQueries({ queryKey: ['items'] })
    void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
    void queryClient.invalidateQueries({ queryKey: ['categories'] })
    void queryClient.invalidateQueries({ queryKey: ['sites'] })
    void queryClient.invalidateQueries({ queryKey: ['runs'] })
  }, [queryClient])

  useEffect(() => {
    const source = new EventSource('/api/events')

    source.onopen = () => setConnection('live')
    source.onerror = () => setConnection('reconnecting')

    source.addEventListener('run.snapshot', (e: MessageEvent) => {
      const data = JSON.parse(e.data) as RunSnapshotData
      const active = data.active_runs[0]
      if (!active) return
      switchToRun(active.id)
      setActiveRun((prev) => (prev?.id === active.id ? prev : ({ ...active } as AgentRun)))
      // always backfill: the filtered response is authoritative (comparing
      // last_seq would be meaningless — filtered viewers hold sparse seqs)
      void getRunEvents(active.id, lastSeqRef.current)
        .then((res) => appendEvents(res.data))
        // recovered by the next snapshot; the SSE reconnect is the retry loop
        .catch(() => {})
    })

    source.addEventListener('run.started', (e: MessageEvent) => {
      const { run } = JSON.parse(e.data) as { run: AgentRun }
      switchToRun(run.id)
      setActiveRun(run)
      void queryClient.invalidateQueries({ queryKey: ['runs'] })
    })

    source.addEventListener('run.event', (e: MessageEvent) => {
      const event = JSON.parse(e.data) as RunEvent
      if (runIdRef.current == null) switchToRun(event.run_id)
      appendEvents([event])
    })

    const onTerminal = (e: MessageEvent) => {
      const { run } = JSON.parse(e.data) as { run: AgentRun }
      setActiveRun((prev) => (prev && prev.id !== run.id ? prev : run))
      invalidateAfterRun()
      if (run.status === 'succeeded' && run.stats) {
        toast.success(`Run complete — ${run.stats.prices_found} prices, ${run.stats.new_listings} new listings`)
      } else if (run.status === 'failed') {
        toast.error(`Run failed${run.error ? ` — ${run.error}` : ''}`)
      }
    }
    source.addEventListener('run.finished', onTerminal)
    source.addEventListener('run.failed', onTerminal)

    return () => source.close()
  }, [appendEvents, invalidateAfterRun, queryClient, switchToRun])

  const triggerMutation = useMutation({
    mutationFn: triggerRun,
    onSuccess: ({ run }) => {
      switchToRun(run.id)
      setActiveRun(run)
      setPanelOpen(true)
    },
    onError: (error) => {
      if (error instanceof ApiError && error.code === 'run_in_progress') {
        toast.info('A run is already in progress — showing live activity')
        setPanelOpen(true)
      } else {
        toast.error(error instanceof Error ? error.message : 'Could not start the run')
      }
    },
  })

  const value = useMemo<RunEventsContextValue>(
    () => ({
      activeRun,
      events,
      connection,
      panelOpen,
      setPanelOpen,
      trigger: (req) => triggerMutation.mutate(req),
      isTriggering: triggerMutation.isPending,
    }),
    [activeRun, events, connection, panelOpen, triggerMutation],
  )

  return <RunEventsContext.Provider value={value}>{children}</RunEventsContext.Provider>
}

export function isRunActive(run: AgentRun | null): boolean {
  return run != null && (run.status === 'queued' || run.status === 'running')
}
