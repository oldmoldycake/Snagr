import { describe, expect, it } from 'vitest'
import type { Listing } from '@/api/types'
import { labelFlipsLeft, labeledTicks, makeRail } from './rail'

// Item 3's 30 active listings on 2026-09-21 (target $20.00) — the board that
// packed thirteen $6–$10 rows into 6% of a linear rail.
const ITEM_3 = [
  600, 650, 699, 700, 700, 799, 799, 800, 899, 945, 945, 977, 999, 1000, 1050, 1149, 1899, 2298,
  2400, 2743, 2995, 2999, 2999, 3000, 3999, 4180, 4200, 4998, 5800, 6500,
]

function rows(cents: number[]): Listing[] {
  return cents.map((c, i) => ({ id: i + 1, latest_price: (c / 100).toFixed(2) }) as Listing)
}

const none = new Map<number, number>()

describe('makeRail', () => {
  const rail = makeRail(rows(ITEM_3), none, 2000)!

  it('runs pricier → cheaper, left to right', () => {
    const pcts = [...new Set(ITEM_3)].sort((a, b) => b - a).map((c) => rail.place(c).pct)
    for (let i = 1; i < pcts.length; i++) expect(pcts[i]).toBeGreaterThan(pcts[i - 1])
  })

  it('puts the target mid-rail and spreads the cheap cluster', () => {
    expect(rail.targetPct).toBeCloseTo(49.5, 1)
    expect(rail.place(600).pct - rail.place(1000).pct).toBeGreaterThanOrEqual(15)
  })

  it('ticks at 1-2-5 × 10ⁿ inside the domain', () => {
    expect(rail.ticks.map((t) => t.cents)).toEqual([5000, 2000, 1000])
  })

  it('falls back to even round steps in a tight band', () => {
    // the mock GPU: every listing between $550 and $647
    const tight = makeRail(rows([55065, 59572, 60739, 61537, 62555, 64657]), none, 55000)!
    expect(tight.ticks.map((t) => t.cents)).toEqual([65000, 60000, 55000])
  })

  it('clamps folded rows outside the domain', () => {
    expect(rail.place(7999).clamp).toBe('«')
    expect(rail.place(125).clamp).toBe('»')
    expect(rail.place(125).pct).toBe(100)
  })

  it('includes range-start prices in the domain', () => {
    const drifted = makeRail(rows([1000]), new Map([[1, 9000]]), null)!
    expect(drifted.place(9000).clamp).toBeNull()
  })

  it.each([
    ['no prices', [], null],
    ['one price', [1500], null],
    ['all equal', [1500, 1500, 1500], 1500],
    ['a 1¢ price', [1, 1500], 2000],
  ])('stays finite with %s', (_, cents, target) => {
    const r = makeRail(rows(cents), none, target)
    if (cents.length === 0) return expect(r).toBeNull()
    for (const c of cents) expect(Number.isFinite(r!.place(c).pct)).toBe(true)
    if (target != null) expect(Number.isFinite(r!.targetPct!)).toBe(true)
  })

  it('centres a single price', () => {
    expect(makeRail(rows([1500]), none, null)!.place(1500).pct).toBeCloseTo(50)
  })

  it('ignores a zero price', () => {
    expect(makeRail(rows([0]), none, null)).toBeNull()
  })
})

describe('labeledTicks', () => {
  it('lets the ⌖ label name its own spot', () => {
    const rail = makeRail(rows(ITEM_3), none, 2000)!
    expect(labeledTicks(rail, 330)).toEqual([5000, 1000])
  })

  it('drops the 2s when labels would collide', () => {
    const rail = makeRail(rows([100, 100_000]), none, null)!
    expect(labeledTicks(rail, 180)).not.toContain(2000)
    expect(labeledTicks(rail, 180)).toContain(5000)
    expect(labeledTicks(rail, 2000)).toContain(2000)
  })
})

describe('labelFlipsLeft', () => {
  it('stays right in open space', () => {
    expect(labelFlipsLeft(60, 50, '$9.99', 330, 78)).toBe(false)
  })

  it('flips at the rail edge', () => {
    expect(labelFlipsLeft(96, 50, '$6.00', 330, 78)).toBe(true)
  })

  it('flips rather than print across ⌖', () => {
    expect(labelFlipsLeft(45, 50, '$22.98', 330, 78)).toBe(true)
  })

  it('crosses ⌖ only when there is no room on the left', () => {
    expect(labelFlipsLeft(2, 10, '$65.00', 330, 78)).toBe(false)
  })

  it('uses the fallback before the rail is measured', () => {
    expect(labelFlipsLeft(80, 50, '$6.00', 0, 78)).toBe(true)
    expect(labelFlipsLeft(70, 50, '$6.00', 0, 78)).toBe(false)
  })
})
