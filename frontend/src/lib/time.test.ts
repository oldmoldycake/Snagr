import { describe, expect, it } from 'vitest'
import { formatTokens } from './time'

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
