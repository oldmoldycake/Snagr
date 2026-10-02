import { describe, expect, it } from 'vitest'
import type { Site } from '@/api/types'
import { isPaused } from './sitePause'

function site(paused_until: string | null): Site {
  return { id: 1, name: 'ebay.com', paused_until } as Site
}

describe('isPaused', () => {
  const now = Date.parse('2026-10-02T14:00:00Z')

  it('holds a site until its pause lifts', () => {
    expect(isPaused(site('2026-10-02T14:21:00Z'), now)).toBe(true)
  })

  it('lets a site go the moment its pause passes, though paused_until stays set', () => {
    expect(isPaused(site('2026-10-02T14:00:00Z'), now)).toBe(false)
    expect(isPaused(site('2026-10-02T13:59:00Z'), now)).toBe(false)
  })

  it('never calls a site with no pause paused', () => {
    expect(isPaused(site(null), now)).toBe(false)
  })
})
