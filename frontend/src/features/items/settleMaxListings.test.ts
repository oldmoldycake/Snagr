import { describe, expect, it } from 'vitest'
import { settleMaxListings } from './settleMaxListings'

describe('settleMaxListings', () => {
  it('falls back while the field is blank', () => {
    expect(settleMaxListings('', 5)).toBe(5)
    expect(settleMaxListings(' ', 10)).toBe(10)
  })

  it('takes a whole number from 1 to 10 as typed', () => {
    expect(settleMaxListings('8', 5)).toBe(8)
    expect(settleMaxListings('1', 5)).toBe(1)
    expect(settleMaxListings('10', 5)).toBe(10)
  })

  it('holds anything else to 1–10, rounded', () => {
    expect(settleMaxListings('18', 5)).toBe(10)
    expect(settleMaxListings('0', 5)).toBe(1)
    expect(settleMaxListings('-3', 5)).toBe(1)
    expect(settleMaxListings('2.4', 5)).toBe(2)
  })
})
