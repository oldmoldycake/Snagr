import { describe, expect, it } from 'vitest'
import { percentToThreshold, thresholdToPercent } from './thresholds'

describe('thresholdToPercent', () => {
  it('shows a stored threshold as a whole percentage', () => {
    expect(thresholdToPercent('0.85')).toBe('85')
    expect(thresholdToPercent('0.90')).toBe('90')
    expect(thresholdToPercent('0.50')).toBe('50')
    expect(thresholdToPercent('1.00')).toBe('100')
  })

  it('is not thrown off by binary floating point', () => {
    // 0.57 * 100 is 56.99999999999999
    expect(thresholdToPercent('0.57')).toBe('57')
  })
})

describe('percentToThreshold', () => {
  it('sends a percentage as the two-place decimal the API stores', () => {
    expect(percentToThreshold('85')).toBe('0.85')
    expect(percentToThreshold('50')).toBe('0.50')
    expect(percentToThreshold('100')).toBe('1.00')
  })

  it('round-trips every threshold the API accepts', () => {
    for (let percent = 50; percent <= 100; percent++) {
      const threshold = percentToThreshold(String(percent))
      expect(threshold).toBe(`${Math.floor(percent / 100)}.${String(percent % 100).padStart(2, '0')}`)
      expect(thresholdToPercent(threshold)).toBe(String(percent))
    }
  })
})
