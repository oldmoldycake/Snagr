import { describe, expect, it } from 'vitest'
import { DEFAULT_TRACKING, trackingPayload } from './TrackingFields'

describe('trackingPayload', () => {
  it('sends whether replicas are accepted, off for a new item', () => {
    expect(trackingPayload(DEFAULT_TRACKING).allow_reproductions).toBe(false)
    expect(trackingPayload({ ...DEFAULT_TRACKING, allowReproductions: true }).allow_reproductions).toBe(true)
  })
})
