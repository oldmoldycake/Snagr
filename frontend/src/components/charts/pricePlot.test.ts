import { describe, expect, it } from 'vitest'
import { priceDomain, priceSummary, priceTicks, stepStop } from './pricePlot'

const labels = (yMin: number, yMax: number) =>
  priceTicks(yMin, yMax)
    .map((t) => t.label)
    .filter((l) => l != null)

describe('priceTicks', () => {
  it('keeps the 1-2-5 then 1-2.5-5 ladder for everyday spans', () => {
    expect(labels(0, 5)).toEqual(['$1', '$2', '$3', '$4', '$5'])
    expect(labels(500, 540)).toEqual(['$510', '$520', '$530', '$540'])
    expect(labels(400, 500)).toEqual(['$425', '$450', '$475', '$500'])
    expect(labels(0, 20_000)).toEqual(['$5000', '$10000', '$15000', '$20000'])
  })

  it('stays a handful of lines when the target is the largest the column allows', () => {
    const [yMin, yMax] = priceDomain([549.99, 612], 99_999_999.99)!
    const ticks = priceTicks(yMin, yMax)
    expect(ticks.length).toBeLessThanOrEqual(30)
    expect(labels(yMin, yMax)).toEqual(['$25M', '$50M', '$75M', '$100M'])
  })

  it('goes compact past $100k, in one unit with the step precision', () => {
    expect(labels(0, 200_000)).toEqual(['$50k', '$100k', '$150k', '$200k'])
    expect(labels(0, 1_200_000)).toEqual(['$0.25M', '$0.50M', '$0.75M', '$1.00M'])
    expect(labels(0, 10_000_000)).toEqual(['$2.5M', '$5.0M', '$7.5M', '$10.0M'])
  })

  it('labels no wider than the left margin fits, $100000 at most', () => {
    for (const yMax of [99_990, 150_000, 999_990, 5_000_000, 100_000_000]) {
      for (const l of labels(0, yMax)) expect(l.length).toBeLessThanOrEqual(7)
    }
  })
})

describe('priceSummary', () => {
  it('reads low, high, now and target', () => {
    expect(priceSummary([612, 549.99, 580], 580, 500, 'USD')).toBe(
      'low $549.99, high $612.00, now $580.00, target $500.00',
    )
  })

  it('leaves out a missing target and reads a missing now as out of stock', () => {
    expect(priceSummary([10, 20], null, null, 'EUR')).toBe('low €10.00, high €20.00, now out of stock')
  })
})

describe('stepStop', () => {
  it('starts Left at the latest stop and Right at the earliest', () => {
    expect(stepStop(4, null, 'ArrowLeft')).toBe(3)
    expect(stepStop(4, null, 'ArrowRight')).toBe(0)
  })

  it('steps one stop and stops at either end', () => {
    expect(stepStop(4, 2, 'ArrowLeft')).toBe(1)
    expect(stepStop(4, 2, 'ArrowRight')).toBe(3)
    expect(stepStop(4, 0, 'ArrowLeft')).toBe(0)
    expect(stepStop(4, 3, 'ArrowRight')).toBe(3)
  })

  it('jumps with Home and End, and ignores other keys or no stops', () => {
    expect(stepStop(4, 2, 'Home')).toBe(0)
    expect(stepStop(4, 1, 'End')).toBe(3)
    expect(stepStop(4, 1, 'Enter')).toBeNull()
    expect(stepStop(0, null, 'ArrowLeft')).toBeNull()
  })
})
