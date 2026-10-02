import { describe, expect, it } from 'vitest'
import { biggestMovers } from './movers'

const row = (name: string, pct: number) => ({ name, pct })
const names = (rows: { name: string }[]) => rows.map((r) => r.name)

describe('biggestMovers', () => {
  it('orders the bars biggest drop to biggest rise', () => {
    const shown = biggestMovers([row('Up', 4), row('Flat', 0), row('Down', -12), row('Dip', -1), row('Spike', 30)], 15)
    expect(names(shown)).toEqual(['Down', 'Dip', 'Flat', 'Up', 'Spike'])
  })

  it('keeps the biggest rise when drops outnumber the bars', () => {
    const shown = biggestMovers([row('A', -1), row('B', -2), row('C', -3), row('D', -4), row('Rise', 9)], 3)
    expect(names(shown)).toEqual(['D', 'C', 'Rise'])
  })

  it('keeps the biggest drop when rises outnumber the bars', () => {
    const shown = biggestMovers([row('Crash', -60), row('A', 1), row('B', 2), row('C', 3), row('D', 4)], 3)
    expect(names(shown)).toEqual(['Crash', 'C', 'D'])
  })
})
