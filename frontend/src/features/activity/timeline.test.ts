import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Job, JobsSummary, PausedSite } from '@/api/types'
import { formatClock } from '@/lib/time'
import {
  behindSchedule,
  dueState,
  foldQueue,
  groupByHour,
  nextCheckText,
  pausedSiteOf,
  queuedWait,
  recentFailures,
} from './timeline'

// local-time constructors, and clocks through formatClock, so the
// expectations hold in any time zone and locale
const NOW = new Date(2026, 8, 25, 14, 5)
const clock = (h: number) => formatClock(new Date(2026, 8, 25, h, 0))

function job(id: number, finished: Date, status: Job['status'] = 'done'): Job {
  return {
    id,
    status,
    finished_at: finished.toISOString(),
    created_at: finished.toISOString(),
  } as Job
}

describe('foldQueue', () => {
  // queued job ids, soonest first as the API sends them
  const queue = (n: number) => Array.from({ length: n }, (_, i) => i + 1)

  it('shows the next three, soonest first, and folds the rest', () => {
    expect(foldQueue(queue(8), false)).toEqual({ shown: [1, 2, 3], folded: 5 })
  })

  it('shows the whole queue once opened, still counting the fold', () => {
    expect(foldQueue(queue(8), true)).toEqual({ shown: queue(8), folded: 5 })
  })

  it('never folds away a single row', () => {
    expect(foldQueue(queue(4), false)).toEqual({ shown: [1, 2, 3, 4], folded: 0 })
    expect(foldQueue(queue(5), false)).toEqual({ shown: [1, 2, 3], folded: 2 })
  })

  it('has nothing to fold in a short or empty queue', () => {
    expect(foldQueue(queue(2), false)).toEqual({ shown: [1, 2], folded: 0 })
    expect(foldQueue([], false)).toEqual({ shown: [], folded: 0 })
  })
})

describe('groupByHour', () => {
  it('starts a group each time the hour changes, keeping arrival order', () => {
    const jobs = [
      job(1, new Date(2026, 8, 25, 14, 2)),
      job(2, new Date(2026, 8, 25, 13, 40)),
      job(3, new Date(2026, 8, 25, 13, 10)),
      job(4, new Date(2026, 8, 25, 12, 55)),
    ]
    const groups = groupByHour(jobs, NOW)
    expect(groups.map((g) => g.label)).toEqual([clock(14), clock(13), clock(12)])
    expect(groups[1].jobs.map((j) => j.id)).toEqual([2, 3])
  })

  it('names the day once it is not today', () => {
    const groups = groupByHour(
      [job(1, new Date(2026, 8, 24, 22, 15)), job(2, new Date(2026, 8, 18, 9, 0))],
      NOW,
    )
    expect(groups.map((g) => g.label)).toEqual([
      `yesterday ${clock(22)}`,
      `${new Date(2026, 8, 18).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })} ${clock(9)}`,
    ])
  })

  it('keeps the same hour on different days apart', () => {
    const groups = groupByHour(
      [job(1, new Date(2026, 8, 25, 9, 0)), job(2, new Date(2026, 8, 24, 9, 30))],
      NOW,
    )
    expect(groups).toHaveLength(2)
  })
})

describe('recentFailures', () => {
  it('keeps failures from the last 24 hours only', () => {
    const jobs = [
      job(1, new Date(2026, 8, 25, 12, 55), 'failed'),
      job(2, new Date(2026, 8, 24, 13, 0), 'failed'),
      job(3, new Date(2026, 8, 25, 13, 0), 'done'),
    ]
    expect(recentFailures(jobs, NOW).map((j) => j.id)).toEqual([1])
  })
})

describe('dueState', () => {
  const at = (secs: number) => new Date(NOW.getTime() + secs * 1000).toISOString()
  const now = NOW.getTime()

  it('counts down to work that is not due yet, whatever is running', () => {
    expect(dueState(at(30), false, now)).toBe('scheduled')
    expect(dueState(at(30), true, now)).toBe('scheduled')
  })

  it('puts due work in line behind running work of its kind', () => {
    expect(dueState(at(-5), true, now)).toBe('in-line')
    expect(dueState(at(-30 * 60), true, now)).toBe('in-line')
  })

  it('gives the hunter a minute to wake before due work is overdue', () => {
    expect(dueState(at(-60), false, now)).toBe('scheduled')
    expect(dueState(at(-61), false, now)).toBe('overdue')
  })
})

describe('pausedSiteOf', () => {
  const now = NOW.getTime()
  const at = (mins: number) => new Date(now + mins * 60_000).toISOString()
  const failed = { id: 1, kind: 'hunt', status: 'failed', site_id: 7 } as Job
  const pause = (site_id: number, until: string): PausedSite => ({
    site_id,
    site_name: 'ebay.com',
    paused_until: until,
    paused_reason: '5 consecutive read errors',
  })

  it("finds the pause holding a job's site", () => {
    const held = pause(7, at(39))
    expect(pausedSiteOf(failed, [pause(8, at(10)), held], now)).toBe(held)
  })

  it('lets a job go once its pause has passed, or when its site was never paused', () => {
    expect(pausedSiteOf(failed, [pause(7, at(-1))], now)).toBeUndefined()
    expect(pausedSiteOf(failed, [pause(8, at(39))], now)).toBeUndefined()
  })
})

describe('queuedWait', () => {
  const at = (mins: number) => new Date(NOW.getTime() + mins * 60_000).toISOString()
  const now = NOW.getTime()
  const hunt = (over: Partial<Job> = {}) =>
    ({ id: 1, kind: 'hunt', site_id: 7, reason: 'sweep', run_after: at(-10), ...over }) as Job
  const pause = (until: string): PausedSite => ({
    site_id: 7,
    site_name: 'ebay.com',
    paused_until: until,
    paused_reason: '5 consecutive read errors',
  })
  const open = { pausedSites: [], huntEnabled: true, running: false }

  it('reads a due job with nothing of its kind running as overdue', () => {
    expect(queuedWait(hunt(), open, now)).toEqual({ state: 'overdue' })
  })

  it('reads a due job behind running work as in line', () => {
    expect(queuedWait(hunt(), { ...open, running: true }, now)).toEqual({ state: 'in-line' })
  })

  it('holds a job on a paused site until the pause lifts, however it was queued', () => {
    const paused = { ...open, pausedSites: [pause(at(40))] }
    expect(queuedWait(hunt({ reason: 'user' }), paused, now)).toEqual({
      state: 'site-paused',
      until: at(40),
    })
  })

  it('waits for whichever is later, the pause lifting or the job coming due', () => {
    const job = hunt({ run_after: at(90) })
    expect(queuedWait(job, { ...open, pausedSites: [pause(at(40))] }, now)).toEqual({
      state: 'site-paused',
      until: at(90),
    })
  })

  it('ignores a pause that has already lifted', () => {
    expect(queuedWait(hunt(), { ...open, pausedSites: [pause(at(-1))] }, now)).toEqual({
      state: 'overdue',
    })
  })

  it('holds hunts, and only hunts, while hunting is off', () => {
    const off = { ...open, huntEnabled: false }
    expect(queuedWait(hunt(), off, now)).toEqual({ state: 'hunting-off' })
    expect(queuedWait(hunt({ kind: 'ground', site_id: null }), off, now)).toEqual({
      state: 'overdue',
    })
  })
})

describe('behindSchedule', () => {
  const at = (mins: number) => new Date(NOW.getTime() + mins * 60_000).toISOString()
  const now = NOW.getTime()
  const summary = (over: Partial<JobsSummary> = {}) =>
    ({
      hunts_running: 0,
      checks_running: 0,
      next_check_at: at(5),
      next_hunt_at: at(20),
      ...over,
    }) as JobsSummary

  it('is idle, not behind, while everything is on schedule', () => {
    expect(behindSchedule(summary(), true, now)).toBe(false)
  })

  it('is behind when a check or a hunt is overdue and nothing is running', () => {
    expect(behindSchedule(summary({ next_check_at: at(-5) }), true, now)).toBe(true)
    expect(behindSchedule(summary({ next_hunt_at: at(-5) }), true, now)).toBe(true)
  })

  it('is not behind while work is running — the overdue work is in line', () => {
    expect(behindSchedule(summary({ next_hunt_at: at(-5), hunts_running: 1 }), true, now)).toBe(
      false,
    )
    expect(behindSchedule(summary({ next_check_at: at(-5), checks_running: 3 }), true, now)).toBe(
      false,
    )
  })

  it('does not count hunts held while hunting is off', () => {
    expect(behindSchedule(summary({ next_hunt_at: at(-5) }), false, now)).toBe(false)
  })
})

describe('nextCheckText', () => {
  const at = (secs: number) => new Date(NOW.getTime() + secs * 1000).toISOString()
  const now = NOW.getTime()

  afterEach(() => {
    vi.useRealTimers()
  })

  it('counts down to a check still ahead', () => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
    expect(nextCheckText(at(12 * 60), now)).toBe('next check in 12m')
  })

  it('says a due check is starting, never a bare "now" beside "Idle"', () => {
    expect(nextCheckText(at(0), now)).toBe('next check starting')
    expect(nextCheckText(at(-60), now)).toBe('next check starting')
  })

  it('says a late check is overdue', () => {
    expect(nextCheckText(at(-61), now)).toBe('next check overdue')
  })
})
