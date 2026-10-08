import type { Job, JobsSummary, PausedSite } from '@/api/types'
import { countdown, formatClock, isOverdue } from '@/lib/time'

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

/**
 * Where queued work stands. The hunter runs a fixed number of each kind of job
 * at once and wakes at least every 30 s, so work that is due waits `in-line`
 * behind a running job of its kind, and with none running is `overdue` once a
 * minute has passed. Until then, and until it is due at all, it is `scheduled`.
 */
export type DueState = 'scheduled' | 'in-line' | 'overdue'

/** Where work due at `iso` stands, given whether work of its kind is running now. */
export function dueState(iso: string, running: boolean, now: number = Date.now()): DueState {
  if (Date.parse(iso) > now) return 'scheduled'
  if (running) return 'in-line'
  return isOverdue(iso, now) ? 'overdue' : 'scheduled'
}

/** Where the soonest price check stands; with no summary yet, on schedule. */
export function checksDue(summary: JobsSummary | undefined, now: number = Date.now()): DueState {
  if (!summary?.next_check_at) return 'scheduled'
  return dueState(summary.next_check_at, summary.checks_running > 0, now)
}

/**
 * Why a queued job hasn't started, which its row says in place of a bare
 * countdown: the hunter's own schedule (DueState), a paused site, whose jobs
 * it skips until the pause lifts, or hunting switched off on this server.
 */
export type QueuedWait =
  | { state: DueState }
  | { state: 'site-paused'; until: string }
  | { state: 'hunting-off' }

interface QueueContext {
  pausedSites: PausedSite[]
  huntEnabled: boolean
  /** whether a job of this kind is running now */
  running: boolean
}

/** The pause holding `job`'s site now, if one is: the hunter won't run the job until it lifts. */
export function pausedSiteOf(
  job: Job,
  pausedSites: PausedSite[],
  now: number = Date.now(),
): PausedSite | undefined {
  return pausedSites.find(
    (site) => site.site_id === job.site_id && Date.parse(site.paused_until) > now,
  )
}

/** Why `job` is still in the queue (see QueuedWait). */
export function queuedWait(job: Job, context: QueueContext, now: number = Date.now()): QueuedWait {
  const paused = pausedSiteOf(job, context.pausedSites, now)
  if (paused) {
    // the later of the two, as the summary's next_hunt_at counts it
    const until =
      Date.parse(job.run_after) > Date.parse(paused.paused_until)
        ? job.run_after
        : paused.paused_until
    return { state: 'site-paused', until }
  }
  if (job.kind === 'hunt' && !context.huntEnabled) return { state: 'hunting-off' }
  return { state: dueState(job.run_after, context.running, now) }
}

/**
 * True when no hunt or price check is running though work is overdue — when
 * "idle" would contradict the queue. Hunts held while hunting is off are not
 * late; they are waiting on the operator.
 */
export function behindSchedule(
  summary: JobsSummary,
  huntEnabled: boolean,
  now: number = Date.now(),
): boolean {
  if (summary.hunts_running + summary.checks_running > 0) return false
  return (
    isOverdue(summary.next_check_at, now) || (huntEnabled && isOverdue(summary.next_hunt_at, now))
  )
}

/**
 * "next check …" for the dashboard strip, where it sits beside "Idle".
 * `countdown`'s bare "now" there reads as a contradiction: a check that is due
 * but not yet late is about to start, and one that is late is overdue (the
 * strip then reads "Behind schedule", not "Idle").
 */
export function nextCheckText(iso: string, now: number = Date.now()): string {
  if (isOverdue(iso, now)) return 'next check overdue'
  if (Date.parse(iso) <= now) return 'next check starting'
  return `next check ${countdown(iso)}`
}
