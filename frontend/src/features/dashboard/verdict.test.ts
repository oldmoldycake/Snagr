import { describe, expect, it } from 'vitest'
import type { ItemSummary } from '@/api/types'
import { namedHits, standing } from './verdict'

/** An item whose target_met follows from its prices, like the API's. */
function item(
  id: number,
  name: string,
  best: string | null,
  target: string | null = '100.00',
  watchTarget: string | null = null,
): ItemSummary {
  const effective = watchTarget ?? target
  const met = best != null && effective != null && Number(best) <= Number(effective)
  return {
    id,
    name,
    best_price: best,
    target_price: target,
    target_met: met,
    watch: { target_price: watchTarget },
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

describe('standing', () => {
  it('picks the item closest to its target by share of the target, skipping items at target', () => {
    const result = standing([
      item(1, 'At target', '90.00'),
      item(2, 'Cheap but far', '20.00', '10.00'),
      item(3, 'Near', '110.00'),
      item(4, 'Unpriced', null),
      item(5, 'No target', '5.00', null),
    ])
    expect(result).toEqual({ kind: 'closest', item: expect.objectContaining({ name: 'Near' }), gapCents: 1000 })
  })

  it("measures against the watch's own target over the item's", () => {
    const result = standing([item(1, 'Overridden', '150.00', null, '120.00')])
    expect(result).toEqual({ kind: 'closest', item: expect.objectContaining({ name: 'Overridden' }), gapCents: 3000 })
  })

  it('has nothing to add when every item with a price and a target is at target', () => {
    expect(standing([item(1, 'At target', '90.00'), item(2, 'Unpriced', null)])).toBeNull()
  })

  it('says no targets, not no prices, when items are priced but none has a target', () => {
    expect(standing([item(1, 'Priced', '120.00', null), item(2, 'Unpriced', null, null)])).toEqual({
      kind: 'no_targets',
    })
  })

  it('says no prices when nothing has a price, target or not', () => {
    expect(standing([item(1, 'Targeted', null), item(2, 'Untargeted', null, null)])).toEqual({
      kind: 'no_prices',
      elsewhere: false,
    })
  })

  it('says no prices for the items with a target when only items without one are priced', () => {
    expect(standing([item(1, 'Targeted', null), item(2, 'Priced', '120.00', null)])).toEqual({
      kind: 'no_prices',
      elsewhere: true,
    })
  })
})
