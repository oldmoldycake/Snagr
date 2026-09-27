import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { countdown, formatTokens } from './time'

describe('formatTokens', () => {
  it('shows small counts as they are', () => {
    expect(formatTokens(0)).toBe('0')
    expect(formatTokens(999)).toBe('999')
  })

  it('switches to thousands, then millions', () => {
    expect(formatTokens(12_400)).toBe('12.4k')
    expect(formatTokens(1_829_400)).toBe('1.8M')
  })

  it('never renders "1000.0k" at the boundary', () => {
    expect(formatTokens(999_940)).toBe('999.9k')
    expect(formatTokens(999_950)).toBe('1.0M')
  })
})

describe('countdown', () => {
  const NOW = new Date('2026-09-27T18:00:00Z').getTime()
  const at = (secs: number) => new Date(NOW + secs * 1000).toISOString()

  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW)
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('counts down to a time ahead', () => {
    expect(countdown(at(42))).toBe('in 0:42')
    expect(countdown(at(12 * 60))).toBe('in 12m')
    expect(countdown(at(4 * 3600 + 12 * 60))).toBe('in 4h 12m')
  })

  it('says "now" for a time that has only just passed', () => {
    expect(countdown(at(0))).toBe('now')
    expect(countdown(at(-60))).toBe('now')
  })

  it('says "overdue" rather than "now" for a time long past', () => {
    expect(countdown(at(-61))).toBe('overdue')
    expect(countdown(at(-50 * 60))).toBe('overdue')
  })
})
