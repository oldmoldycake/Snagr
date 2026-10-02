import type { Job } from '@/api/types'
import { formatClock } from '@/lib/time'

/** How far back a failed hunt still asks for attention. */
export const FAILURE_WINDOW_MS = 24 * 60 * 60 * 1000

/** How many queued jobs show above "now" before the rest fold away. */
const QUEUE_PREVIEW = 3

/**
 * The queued jobs to show, kept in the order they arrive (the API's soonest
 * first), and how many fold behind "Show N more". `folded` holds while the
 * fold is open, so "Show fewer" can still be offered. Folding away a single
 * row saves nothing, so a queue one past the preview shows in full.
 */
export function foldQueue<T>(queued: T[], open: boolean): { shown: T[]; folded: number } {
  if (queued.length <= QUEUE_PREVIEW + 1) return { shown: queued, folded: 0 }
  return {
    shown: open ? queued : queued.slice(0, QUEUE_PREVIEW),
    folded: queued.length - QUEUE_PREVIEW,
  }
}

/** One hour of finished work, as the timeline heads it. */
export interface HourGroup {
  key: string
  /** `2:00 PM` today, `yesterday 10:00 PM` or `Sep 18 2:00 PM` before that (24-hour where the locale is) */
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
  const top = new Date(at)
  top.setMinutes(0, 0, 0)
  const hour = formatClock(top)
  if (at.toDateString() === now.toDateString()) return hour
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (at.toDateString() === yesterday.toDateString()) return `yesterday ${hour}`
  return `${at.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${hour}`
}

/** `2:02 PM` / `14:02` — a row's time; its hour heading already names the day. */
export function rowTime(iso: string): string {
  return formatClock(new Date(iso))
}

/** The failed jobs recent enough that someone should still look at them. */
export function recentFailures(jobs: Job[], now: Date = new Date()): Job[] {
  return jobs.filter((job) => {
    if (job.status !== 'failed' || job.finished_at == null) return false
    return now.getTime() - new Date(job.finished_at).getTime() <= FAILURE_WINDOW_MS
  })
}
