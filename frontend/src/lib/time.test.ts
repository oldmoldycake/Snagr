import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { countdown, dayPhrase, formatDate, formatDateTime, formatTokens, isOverdue } from './time'

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

  it('agrees with isOverdue on where "now" ends', () => {
    expect(isOverdue(at(-60))).toBe(false)
    expect(isOverdue(at(-61))).toBe(true)
    expect(isOverdue(at(30))).toBe(false)
    expect(isOverdue(null)).toBe(false)
  })
})

describe('formatDateTime', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 8, 27, 18, 0))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('leaves the year out for this year and names it for any other', () => {
    expect(formatDateTime(new Date(2026, 8, 25, 10, 3).toISOString())).not.toContain('2026')
    expect(formatDateTime(new Date(2027, 0, 5, 10, 3).toISOString())).toContain('2027')
  })

  it('shows a dash rather than "Invalid Date"', () => {
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('not a date')).toBe('—')
  })
})

describe('formatDate', () => {
  it('always names the year', () => {
    expect(formatDate(new Date(2026, 9, 2).toISOString())).toContain('2026')
  })
})

describe('dayPhrase', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 9, 2, 9, 0))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('names today and yesterday by the calendar, not the last 24 hours', () => {
    expect(dayPhrase(new Date(2026, 9, 2, 0, 5).toISOString())).toBe('today')
    expect(dayPhrase(new Date(2026, 9, 1, 23, 0).toISOString())).toBe('yesterday')
    expect(dayPhrase(new Date(2026, 9, 1, 0, 5).toISOString())).toBe('yesterday')
  })

  it('dates anything older, with the year once it is not this one', () => {
    const older = dayPhrase(new Date(2026, 8, 24, 10, 3).toISOString())
    expect(older).toMatch(/^on /)
    expect(older).not.toContain('2026')
    expect(dayPhrase(new Date(2025, 11, 18, 10, 3).toISOString())).toMatch(/^on .*2025/)
  })

  it('shows a dash rather than "on Invalid Date"', () => {
    expect(dayPhrase(null)).toBe('—')
    expect(dayPhrase('not a date')).toBe('—')
  })
})
