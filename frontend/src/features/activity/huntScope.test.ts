import { describe, expect, it } from 'vitest'
import { qk } from '@/api/queries'
import type { Category, ItemSummary } from '@/api/types'
import { itemCategories, plannedHunts } from './huntScope'

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

describe('plannedHunts', () => {
  const categories = [
    { id: 1, site_ids: [1, 2, 3] },
    { id: 2, site_ids: [2] },
  ] as Category[]
  const items = [
    { id: 10, category_id: 1, site_ids: null },
    { id: 11, category_id: 1, site_ids: [3] },
    { id: 12, category_id: 2, site_ids: null },
  ] as ItemSummary[]

  it("counts a hunt per site each item searches, its own sites or else its category's", () => {
    expect(plannedHunts({ scope: 'category', scope_id: 1 }, items, categories)).toBe(4)
    expect(plannedHunts({ scope: 'item', scope_id: 10 }, items, categories)).toBe(3)
    expect(plannedHunts({ scope: 'global' }, items, categories)).toBe(5)
  })

  it('counts a site by the items that search it', () => {
    expect(plannedHunts({ scope: 'site', scope_id: 2 }, items, categories)).toBe(2)
    expect(plannedHunts({ scope: 'site', scope_id: 3 }, items, categories)).toBe(2)
    expect(plannedHunts({ scope: 'site', scope_id: 9 }, items, categories)).toBe(0)
  })
})
