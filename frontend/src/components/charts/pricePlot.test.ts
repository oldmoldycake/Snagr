import { describe, expect, it } from 'vitest'
import { priceDomain, priceTicks } from './pricePlot'

const majors = (yMin: number, yMax: number) =>
  priceTicks(yMin, yMax)
    .filter((t) => t.major)
    .map((t) => t.v)

describe('priceTicks', () => {
  it('keeps the 1-2-5 then 1-2.5-5 ladder for everyday spans', () => {
    expect(majors(0, 5)).toEqual([1, 2, 3, 4, 5])
    expect(majors(500, 540)).toEqual([510, 520, 530, 540])
    expect(majors(400, 500)).toEqual([425, 450, 475, 500])
    expect(majors(0, 20_000)).toEqual([5000, 10_000, 15_000, 20_000])
  })

  it('stays a handful of lines when the target is the largest the column allows', () => {
    const [yMin, yMax] = priceDomain([549.99, 612], 99_999_999.99)!
    const ticks = priceTicks(yMin, yMax)
    expect(ticks.length).toBeLessThanOrEqual(30)
    expect(ticks.filter((t) => t.major).map((t) => t.v)).toEqual([
      25_000_000, 50_000_000, 75_000_000, 100_000_000,
    ])
  })
})
