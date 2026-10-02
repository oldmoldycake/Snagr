import { describe, expect, it } from 'vitest'
import type { Job } from '@/api/types'
import { formatClock } from '@/lib/time'
import { foldQueue, groupByHour, recentFailures } from './timeline'

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
