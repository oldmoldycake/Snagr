import { describe, expect, it } from 'vitest'
import type { PriceCheck } from '@/api/types'
import { checkLevel } from './checkLevel'

function check(overrides: Partial<PriceCheck>): PriceCheck {
  return {
    id: 1,
    listing_id: 1,
    site_name: 'eBay',
    price: '549.99',
    currency: 'USD',
    in_stock: true,
    status: 'ok',
    method: 'llm',
    confirmed: true,
    checked_at: '2026-10-01T12:00:00Z',
    ...overrides,
  }
}

describe('checkLevel', () => {
  it('ticks a price you could buy at, or one whose stock is unknown', () => {
    expect(checkLevel(check({ in_stock: true }))).toBe('success')
    expect(checkLevel(check({ in_stock: null }))).toBe('success')
  })

  it('gives an out-of-stock reading the neutral mark, not the tick', () => {
    expect(checkLevel(check({ in_stock: false }))).toBe('info')
  })

  it('warns on a failed check and marks a sold or ended listing as gone', () => {
    expect(checkLevel(check({ status: 'error' }))).toBe('warn')
    expect(checkLevel(check({ status: 'sold' }))).toBe('error')
    expect(checkLevel(check({ status: 'ended' }))).toBe('error')
  })
})
