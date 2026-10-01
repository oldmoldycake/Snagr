import { describe, expect, it } from 'vitest'
import { qk } from '@/api/queries'
import { itemCategories } from './huntScope'

describe('itemCategories', () => {
  it('maps items from list pages and item details', () => {
    const cached: [readonly unknown[], unknown][] = [
      [qk.items({ category_id: 1 }), { data: [{ id: 10, category_id: 1 }], meta: {} }],
      [qk.item(20), { id: 20, category_id: 2 }],
    ]
    expect(itemCategories(cached)).toEqual(
      new Map([
        [10, 1],
        [20, 2],
      ]),
    )
  })

  it('ignores the queries nested under a detail and ones not yet loaded', () => {
    const cached: [readonly unknown[], unknown][] = [
      [qk.itemHistory(20, '30d'), { points: [] }],
      [qk.itemChecks(20), { data: [{ id: 99, category_id: 5 }] }],
      [qk.items({ category_id: 3 }), undefined],
    ]
    expect(itemCategories(cached).size).toBe(0)
  })
})
