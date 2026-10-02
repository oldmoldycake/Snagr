import { describe, expect, it } from 'vitest'
import type { Job, JobEvent } from '@/api/types'
import { eventsForLive, listingMentions } from './jobEvents'

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

describe('listingMentions', () => {
  it('cuts out the listing a save names', () => {
    expect(listingMentions('Saved as listing #22932 — "GBA cart" (match 91)')).toEqual([
      { text: 'Saved as ', listing: false },
      { text: 'listing #22932', listing: true },
      { text: ' — "GBA cart" (match 91)', listing: false },
    ])
  })

  it('cuts out every listing a replacement names, wherever they fall', () => {
    expect(listingMentions('Replaced listing #12 "Old" with listing #34')).toEqual([
      { text: 'Replaced ', listing: false },
      { text: 'listing #12', listing: true },
      { text: ' "Old" with ', listing: false },
      { text: 'listing #34', listing: true },
    ])
  })

  it('leaves a line that names no listing whole', () => {
    expect(listingMentions('Searched "gba" · 6 results, 2 already tracked')).toEqual([
      { text: 'Searched "gba" · 6 results, 2 already tracked', listing: false },
    ])
    expect(listingMentions('tracking 3 of 5 listings')).toEqual([
      { text: 'tracking 3 of 5 listings', listing: false },
    ])
  })
})
