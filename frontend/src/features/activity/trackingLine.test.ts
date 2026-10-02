import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { HuntFacts, ItemDetail } from '@/api/types'
import { trackingCount, trackingLine } from './trackingLine'

const NOW = new Date('2026-09-27T18:00:00Z').getTime()
const at = (mins: number) => new Date(NOW + mins * 60_000).toISOString()

function detail(hunt: Partial<HuntFacts> = {}, max = 5): ItemDetail {
  return {
    max_listings: max,
    hunt: {
      enabled: true,
      running: false,
      next_at: null,
      last_at: null,
      last_result: null,
      slots_open: 0,
      backoff_minutes: null,
      ...hunt,
    },
  } as ItemDetail
}

beforeEach(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterEach(() => {
  vi.useRealTimers()
})

describe('trackingCount', () => {
  it('counts tracked listings against the limit', () => {
    expect(trackingCount(4, 5)).toBe('tracking 4 of 5 listings')
    expect(trackingCount(0, 1)).toBe('tracking 0 of 1 listing')
  })

  it('says how far over the limit a watch is rather than clamping', () => {
    expect(trackingCount(6, 5)).toBe('tracking 6 of 5 listings · 1 over the limit')
  })
})

describe('trackingLine', () => {
  it('says how many more it is looking for and when it looks next', () => {
    const hunt = { next_at: at(12), last_at: at(-24 * 60), last_result: 'nothing' } as const
    expect(trackingLine(detail(hunt), 4, false)).toBe(
      'tracking 4 of 5 listings · looking for 1 more · next hunt in 12m · last hunt 1d ago, nothing new',
    )
  })

  it('says a hunt was put off after finding nothing', () => {
    expect(trackingLine(detail({ next_at: at(4), backoff_minutes: 60 }), 3, false)).toBe(
      'tracking 3 of 5 listings · looking for 2 more · next hunt in 4m (slowed down after finding nothing)',
    )
  })

  it('says a full watch waits for room, and judges its last hunt by that', () => {
    expect(trackingLine(detail({ last_at: at(-60), last_result: 'nothing' }), 5, false)).toBe(
      'tracking 5 of 5 listings · automatic hunts wait until you stop tracking one · last hunt 1h ago, nothing better',
    )
  })

  it('treats a watch over its limit as full', () => {
    expect(trackingLine(detail({ next_at: at(12) }), 6, false)).toBe(
      'tracking 6 of 5 listings · 1 over the limit · automatic hunts wait until you stop tracking one',
    )
  })

  it('has no next hunt for a watch whose hunting is off', () => {
    expect(trackingLine(detail({ enabled: false, next_at: at(12) }), 0, false)).toBe(
      'tracking 0 of 5 listings · hunting off — only when you press Hunt now',
    )
  })

  it('says when hunting is off for the whole server', () => {
    expect(trackingLine(detail({ next_at: at(12), last_at: at(-60), last_result: 'found' }), 2, true)).toBe(
      'tracking 2 of 5 listings · hunting is off on this server',
    )
  })
})
