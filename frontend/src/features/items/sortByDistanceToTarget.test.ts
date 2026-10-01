import { describe, expect, it } from 'vitest'
import type { ItemSummary } from '@/api/types'
import { sortByDistanceToTarget } from './WatchList'

function item(name: string, best: string | null, target = '100.00', met = false): ItemSummary {
  return {
    name,
    best_price: best,
    target_price: target,
    target_met: met,
    watch: { target_price: null },
  } as ItemSummary
}

const names = (items: ItemSummary[]) => items.map((i) => i.name)

describe('sortByDistanceToTarget', () => {
  it('orders unpriced items by name', () => {
    const sorted = sortByDistanceToTarget([item('Zelda', null), item('Mario', null), item('Asteroids', null)])
    expect(names(sorted)).toEqual(['Asteroids', 'Mario', 'Zelda'])
  })

  it('puts in-range first, then closest to target, then unpriced', () => {
    const sorted = sortByDistanceToTarget([
      item('Unpriced', null),
      item('Far', '200.00'),
      item('Met', '90.00', '100.00', true),
      item('Near', '110.00'),
    ])
    expect(names(sorted)).toEqual(['Met', 'Near', 'Far', 'Unpriced'])
  })

  it('breaks an equal distance by name', () => {
    const sorted = sortByDistanceToTarget([item('B', '150.00'), item('A', '150.00')])
    expect(names(sorted)).toEqual(['A', 'B'])
  })
})
