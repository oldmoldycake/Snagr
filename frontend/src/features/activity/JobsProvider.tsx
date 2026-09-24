/**
 * One EventSource per session, shared app-wide. Feeds the Activity page, the
 * dashboard ticker, the masthead pill and the activity sheet, and invalidates
 * queries as the hunter works.
 *
 * Two shapes of state, because the hunter does two shapes of work. Hunts have
 * a voice: `live` holds the running ones and `events` their logs, both
 * rebuilt from the snapshot on every (re)connect. A queued hunt is not live —
 * with perpetual hunting nearly every watch has one waiting, and the item
 * page counts those down instead. Checks have a pulse:
 * `checks` is a ring buffer of the last 50 `listing.checked` frames, held only
 * in this tab and never fetched — there is no endpoint for "the last fifty
 * checks", because 2,400 rows a day is a heartbeat, not history.
 *
 * Reconnect contract: the server sends `job.snapshot` on every (re)connect; we
 * refetch GET /api/jobs/:id/events?after_seq=<highest seq held> per live job
 * and merge by seq. Never infer missed events from seq arithmetic — last_seq
 * is the job's global write cursor.
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
import { enqueueJobs, getJobEvents } from '@/api/endpoints'
import { ApiError } from '@/api/client'
import type {
  Job,
  JobCreateRequest,
  JobEvent,
  JobScope,
  JobSnapshotData,
  ListingChecked,
} from '@/api/types'

type Connection = 'live' | 'reconnecting'

/** The tail is what this tab has seen, not what happened — 50 lines is about
 *  a screenful and a half at the terminal's line height. */
const CHECK_TAIL = 50

interface JobsContextValue {
  /** every running hunt and ground job this viewer may see */
  live: Job[]
  /** seq-ordered events per live job */
  events: Map<number, JobEvent[]>
  /** the last CHECK_TAIL price checks, newest last */
  checks: ListingChecked[]
  connection: Connection
  panelOpen: boolean
  setPanelOpen: (open: boolean) => void
  enqueue: (body: JobCreateRequest) => void
  isEnqueuing: boolean
  /** the live hunt covering a scope, if one is already running */
  liveHuntFor: (scope: JobScope, scopeId?: number) => Job | undefined
}

const JobsContext = createContext<JobsContextValue | null>(null)

/** The shared jobs stream; throws outside JobsProvider so a missing provider fails loudly. */
export function useJobs(): JobsContextValue {
  const ctx = useContext(JobsContext)
  if (!ctx) throw new Error('useJobs must be used inside JobsProvider')
  return ctx
}

/** Owns the app's one EventSource and the jobs state built from it. */
export function JobsProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [live, setLive] = useState<Job[]>([])
  const [events, setEvents] = useState<Map<number, JobEvent[]>>(new Map())
  const [checks, setChecks] = useState<ListingChecked[]>([])
  const [connection, setConnection] = useState<Connection>('live')
  const [panelOpen, setPanelOpen] = useState(false)
  const eventsRef = useRef(events)
  eventsRef.current = events

  const mergeEvents = useCallback((jobId: number, incoming: JobEvent[]) => {
    if (incoming.length === 0) return
    setEvents((prev) => {
      const held = prev.get(jobId) ?? []
      const seen = new Set(held.map((e) => e.seq))
      const fresh = incoming.filter((e) => !seen.has(e.seq))
      if (fresh.length === 0) return prev
      const next = new Map(prev)
      next.set(jobId, [...held, ...fresh].sort((a, b) => a.seq - b.seq))
      return next
    })
  }, [])

  useEffect(() => {
    const source = new EventSource('/api/events')

    source.onopen = () => setConnection('live')
    source.onerror = () => setConnection('reconnecting')

    source.addEventListener('job.snapshot', (e: MessageEvent) => {
      const { jobs } = JSON.parse(e.data) as JobSnapshotData
      const running = jobs.filter((job) => job.status === 'running')
      setLive(running)
      // always backfill: the filtered response is authoritative, and
      // comparing last_seq would tell us nothing we could act on
      for (const job of running) {
        const held = eventsRef.current.get(job.id) ?? []
        const after = held.length > 0 ? held[held.length - 1].seq : 0
        void getJobEvents(job.id, after)
          .then((res) => mergeEvents(job.id, res.data))
          // recovered by the next snapshot; the SSE reconnect is the retry loop
          .catch(() => {})
      }
    })

    const onLifecycle = (e: MessageEvent) => {
      const { job } = JSON.parse(e.data) as { job: Job }
      setLive((prev) => {
        const rest = prev.filter((j) => j.id !== job.id)
        return job.status === 'running' ? [...rest, job] : rest
      })
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
      if (job.status !== 'running') {
        // a finished hunt may have saved listings and prices anywhere in its
        // watch — cheap to refetch, and the alternative is a stale page
        void queryClient.invalidateQueries({ queryKey: ['items'] })
        void queryClient.invalidateQueries({ queryKey: ['dashboard'] })
        void queryClient.invalidateQueries({ queryKey: ['categories'] })
      }
    }
    source.addEventListener('job.started', onLifecycle)
    source.addEventListener('job.finished', onLifecycle)
    source.addEventListener('job.failed', onLifecycle)

    source.addEventListener('job.event', (e: MessageEvent) => {
      const event = JSON.parse(e.data) as JobEvent
      mergeEvents(event.job_id, [event])
      // the breaker tripping changes what the whole page says next
      if (event.event_type === 'site_paused') {
        void queryClient.invalidateQueries({ queryKey: ['jobs', 'summary'] })
        void queryClient.invalidateQueries({ queryKey: ['sites'] })
      }
    })

    source.addEventListener('listing.checked', (e: MessageEvent) => {
      const check = JSON.parse(e.data) as ListingChecked
      setChecks((prev) => [...prev, check].slice(-CHECK_TAIL))
      void queryClient.invalidateQueries({ queryKey: ['jobs', 'summary'] })
      void queryClient.invalidateQueries({ queryKey: ['items', 'detail', check.item_id] })
    })

    return () => source.close()
  }, [mergeEvents, queryClient])

  const enqueueMutation = useMutation({
    mutationFn: enqueueJobs,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['jobs'] }),
    onError: (error) => {
      toast.error(
        error instanceof ApiError ? error.message : 'Could not ask the hunter for that',
      )
    },
  })

  const liveHuntFor = useCallback(
    (scope: JobScope, scopeId?: number) => {
      const hunts = live.filter((job) => job.kind === 'hunt')
      if (scope === 'item') return hunts.find((job) => job.item_id === scopeId)
      if (scope === 'site') return hunts.find((job) => job.site_id === scopeId)
      // a category (or everything) is live when anything in it is — the
      // client has no item -> category map, and does not need one to say so
      return hunts[0]
    },
    [live],
  )

  const value = useMemo<JobsContextValue>(
    () => ({
      live,
      events,
      checks,
      connection,
      panelOpen,
      setPanelOpen,
      enqueue: (body) => enqueueMutation.mutate(body),
      isEnqueuing: enqueueMutation.isPending,
      liveHuntFor,
    }),
    [live, events, checks, connection, panelOpen, enqueueMutation, liveHuntFor],
  )

  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>
}
