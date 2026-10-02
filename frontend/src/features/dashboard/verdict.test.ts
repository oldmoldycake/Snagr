import { describe, expect, it } from 'vitest'
import type { ItemSummary } from '@/api/types'
import { namedHits } from './verdict'

/** An item whose target_met follows from its prices, like the API's. */
function item(id: number, name: string, best: string | null, target: string | null = '100.00'): ItemSummary {
  const met = best != null && target != null && Number(best) <= Number(target)
  return {
    id,
    name,
    best_price: best,
    target_price: target,
    target_met: met,
    watch: { target_price: null },
  } as ItemSummary
}

const names = (items: ItemSummary[]) => items.map((i) => i.name)

describe('namedHits', () => {
  it('names only the items at target, furthest under first', () => {
    const { named, more } = namedHits([
      item(1, 'Above', '120.00'),
      item(2, 'Just under', '99.00'),
      item(3, 'Unpriced', null),
      item(4, 'Well under', '60.00'),
      item(5, 'Exactly', '100.00'),
    ])
    expect(names(named)).toEqual(['Well under', 'Just under', 'Exactly'])
    expect(more).toBe(0)
  })

  it('names nothing when no item is at target', () => {
    expect(namedHits([item(1, 'Above', '120.00'), item(2, 'Unpriced', null)])).toEqual({ named: [], more: 0 })
  })

  it('names two and counts the rest beyond three', () => {
    const { named, more } = namedHits([
      item(1, 'A', '90.00'),
      item(2, 'B', '80.00'),
      item(3, 'C', '70.00'),
      item(4, 'D', '60.00'),
      item(5, 'E', '50.00'),
    ])
    expect(names(named)).toEqual(['E', 'D'])
    expect(more).toBe(3)
  })
})
