import { describe, expect, it } from 'vitest'
import type { Job, JobEvent } from '@/api/types'
import { eventsForLive } from './jobEvents'

const job = (id: number) => ({ id }) as Job
const event = (jobId: number, seq: number) => ({ job_id: jobId, seq }) as JobEvent

describe('eventsForLive', () => {
  it('drops the logs of jobs that are no longer running', () => {
    const events = new Map([
      [1, [event(1, 1), event(1, 2)]],
      [2, [event(2, 1)]],
    ])
    const kept = eventsForLive(events, [job(2)])
    expect([...kept.keys()]).toEqual([2])
    expect(kept.get(2)).toBe(events.get(2))
  })

  it('returns the same map when every held log is still live', () => {
    const events = new Map([[1, [event(1, 1)]]])
    expect(eventsForLive(events, [job(1), job(3)])).toBe(events)
  })

  it('empties out once nothing is running', () => {
    const events = new Map([[1, [event(1, 1)]]])
    expect(eventsForLive(events, []).size).toBe(0)
  })
})
