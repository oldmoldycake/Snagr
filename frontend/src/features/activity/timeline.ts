import type { Job } from '@/api/types'

/** How far back a failed hunt still asks for attention. */
export const FAILURE_WINDOW_MS = 24 * 60 * 60 * 1000

/** One hour of finished work, as the timeline heads it. */
export interface HourGroup {
  key: string
  /** `14:00` today, `yesterday 22:00` or `Sep 18 14:00` before that */
  label: string
  jobs: Job[]
}

/**
 * Finished jobs bucketed by the local hour they finished in, keeping the
 * order they arrive in (the API's newest first). A new group starts whenever
 * the hour changes, so the headings read down the page like a clock.
 */
export function groupByHour(jobs: Job[], now: Date = new Date()): HourGroup[] {
  const groups: HourGroup[] = []
  for (const job of jobs) {
    const at = new Date(job.finished_at ?? job.created_at)
    const key = `${at.toDateString()} ${at.getHours()}`
    const last = groups.at(-1)
    if (last?.key === key) {
      last.jobs.push(job)
    } else {
      groups.push({ key, label: hourLabel(at, now), jobs: [job] })
    }
  }
  return groups
}

function hourLabel(at: Date, now: Date): string {
  const hour = `${String(at.getHours()).padStart(2, '0')}:00`
  if (at.toDateString() === now.toDateString()) return hour
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (at.toDateString() === yesterday.toDateString()) return `yesterday ${hour}`
  return `${at.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} ${hour}`
}

/** `14:02` — a row's time; its hour heading already names the day. */
export function rowTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** The failed jobs recent enough that someone should still look at them. */
export function recentFailures(jobs: Job[], now: Date = new Date()): Job[] {
  return jobs.filter((job) => {
    if (job.status !== 'failed' || job.finished_at == null) return false
    return now.getTime() - new Date(job.finished_at).getTime() <= FAILURE_WINDOW_MS
  })
}
