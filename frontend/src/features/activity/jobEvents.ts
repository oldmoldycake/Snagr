import type { Job, JobEvent } from '@/api/types'

/**
 * The held logs, cut down to the jobs a snapshot says are running. A finished
 * job's log is GET /api/jobs/:id/events's to serve (the job page fetches it
 * once the job leaves `live`), so holding it here only grows a tab left open
 * for days — and a job that ended while the stream was down never sends the
 * job.finished that would have dropped it. Returns `events` itself when
 * nothing is dropped, so React skips the render.
 */
export function eventsForLive(
  events: Map<number, JobEvent[]>,
  live: Job[],
): Map<number, JobEvent[]> {
  const running = new Set(live.map((job) => job.id))
  const kept = new Map([...events].filter(([jobId]) => running.has(jobId)))
  return kept.size === events.size ? events : kept
}
