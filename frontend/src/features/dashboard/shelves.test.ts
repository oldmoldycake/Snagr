import { describe, expect, it } from 'vitest'
import type { Category, ItemSummary } from '@/api/types'
import { defaultOpen, groupShelves, lead, newlyStruck, orderShelves, resolveOpen, type Shelf } from './shelves'

function category(id: number, name: string, siteIds: number[] = [1]): Category {
  return { id, name, slug: name.toLowerCase(), site_ids: siteIds, item_count: 99, snagged_count: 0 }
}

/** An item whose target_met follows from its prices, like the API's. */
function item(id: number, categoryId: number, name: string, best: string | null, target: string | null): ItemSummary {
  const met = best != null && target != null && Number(best) <= Number(target)
  return {
    id,
    name,
    category_id: categoryId,
    best_price: best,
    target_price: target,
    currency: 'USD',
    target_met: met,
    watch: { target_price: null },
  } as ItemSummary
}

function shelf(cat: Category, items: ItemSummary[]): Shelf {
  return groupShelves(items, [cat]).shelves[0]
}

describe('groupShelves', () => {
  const gpus = category(1, 'GPUs')
  const audio = category(2, 'Audio')
  const lenses = category(3, 'Camera lenses')
  const keyboards = category(4, 'Keyboards')
  const items = [
    item(10, 1, 'RTX 4070 Super', '529.99', '480.00'),
    item(11, 1, 'RX 7800 XT', '409.00', '420.00'),
    item(12, 2, 'Moondrop Blessing 3', null, '300.00'),
  ]

  it('makes a shelf for each category holding one of your items, and a row for the rest', () => {
    const { shelves, rows } = groupShelves(items, [gpus, audio, lenses, keyboards])
    expect(shelves.map((s) => s.category.name)).toEqual(['GPUs', 'Audio'])
    expect(rows.map((c) => c.name)).toEqual(['Camera lenses', 'Keyboards'])
  })

  it("counts your items, not the category's instance-wide item_count", () => {
    const [gpuShelf] = groupShelves(items, [gpus]).shelves
    expect(gpuShelf.items).toHaveLength(2)
    expect(gpuShelf.hits).toBe(1)
  })

  it('sorts each shelf closest to target first', () => {
    const [gpuShelf] = groupShelves(items, [gpus]).shelves
    expect(gpuShelf.items.map((i) => i.name)).toEqual(['RX 7800 XT', 'RTX 4070 Super'])
  })

  it('puts the category just created first among the rows, the rest alphabetically', () => {
    const { rows } = groupShelves(items, [gpus, audio, lenses, keyboards], keyboards.id)
    expect(rows.map((c) => c.name)).toEqual(['Keyboards', 'Camera lenses'])
  })
})

describe('orderShelves', () => {
  it('orders no-sites, then strikes (more first), then distance, then no prices, then by name', () => {
    const shelves = [
      shelf(category(1, 'Idle'), [item(1, 1, 'a', null, '10.00')]),
      shelf(category(2, 'Far'), [item(2, 2, 'b', '200.00', '100.00')]),
      shelf(category(3, 'Near'), [item(3, 3, 'c', '105.00', '100.00')]),
      shelf(category(4, 'One hit'), [item(4, 4, 'd', '90.00', '100.00')]),
      shelf(category(5, 'Two hits'), [item(5, 5, 'e', '90.00', '100.00'), item(6, 5, 'f', '1.00', '2.00')]),
      shelf(category(6, 'No sites', []), [item(7, 6, 'g', null, null)]),
      shelf(category(7, 'Also idle'), [item(8, 7, 'h', null, null)]),
    ]
    expect(orderShelves(shelves).map((s) => s.category.name)).toEqual([
      'No sites',
      'Two hits',
      'One hit',
      'Near',
      'Far',
      'Also idle',
      'Idle',
    ])
  })

  it('ranks a no-sites shelf first even when another has strikes', () => {
    const shelves = [
      shelf(category(1, 'Hit'), [item(1, 1, 'a', '90.00', '100.00')]),
      shelf(category(2, 'Bare', []), [item(2, 2, 'b', '90.00', '100.00')]),
    ]
    expect(orderShelves(shelves).map((s) => s.category.name)).toEqual(['Bare', 'Hit'])
  })
})

describe('defaultOpen', () => {
  const few = [1, 2, 3, 4].map((id) => shelf(category(id, `C${id}`), [item(id, id, 'x', '500.00', '100.00')]))

  it('opens every shelf when there are four or fewer', () => {
    expect([...defaultOpen(few)].sort()).toEqual([1, 2, 3, 4])
  })

  it('otherwise opens the shelves with strikes plus the one with the single closest item', () => {
    const many = [
      shelf(category(1, 'Hit'), [item(1, 1, 'a', '90.00', '100.00')]),
      shelf(category(2, 'Far'), [item(2, 2, 'b', '300.00', '100.00')]),
      shelf(category(3, 'Closest'), [item(3, 3, 'c', '110.00', '100.00')]),
      shelf(category(4, 'Farther'), [item(4, 4, 'd', '400.00', '100.00')]),
      shelf(category(5, 'Idle'), [item(5, 5, 'e', null, '100.00')]),
    ]
    expect([...defaultOpen(many)].sort()).toEqual([1, 3])
  })
})

describe('resolveOpen', () => {
  const hitShelf = shelf(category(1, 'GPUs'), [item(1, 1, 'a', '90.00', '100.00'), item(2, 1, 'b', '1.00', '2.00')])
  const defaults = new Set<number>()

  it('uses the default when nothing is stored', () => {
    expect(resolveOpen(undefined, hitShelf, defaults)).toEqual({ open: false, reopened: false })
    expect(resolveOpen(undefined, hitShelf, new Set([1]))).toEqual({ open: true, reopened: false })
  })

  it('keeps a stored collapse while the hit count is the same', () => {
    expect(resolveOpen({ collapsed: true, snaggedAt: 2 }, hitShelf, defaults)).toEqual({ open: false, reopened: false })
  })

  it('reopens a collapsed shelf that has more hits than when it was collapsed', () => {
    expect(resolveOpen({ collapsed: true, snaggedAt: 1 }, hitShelf, defaults)).toEqual({ open: true, reopened: true })
  })

  it('keeps a stored open shelf open', () => {
    expect(resolveOpen({ collapsed: false, snaggedAt: 0 }, hitShelf, defaults)).toEqual({ open: true, reopened: false })
  })
})

describe('lead', () => {
  it('names the first strike and its price', () => {
    const items = [item(1, 1, 'RTX 4070 Super', '529.99', '480.00'), item(2, 1, 'RX 7800 XT', '409.00', '420.00')]
    expect(lead(items)).toEqual({ kind: 'hit', name: 'RX 7800 XT', amount: '$409.00' })
  })

  it('otherwise names the closest priced item and its gap, in cents', () => {
    const items = [item(1, 1, 'Far', '300.10', '100.00'), item(2, 1, 'RTX 4070 Super', '529.99', '480.00')]
    expect(lead(items)).toEqual({ kind: 'closest', name: 'RTX 4070 Super', amount: '$49.99' })
  })

  it('says it is still hunting when nothing has a price', () => {
    expect(lead([item(1, 1, 'a', null, '100.00')])).toEqual({ kind: 'idle' })
  })

  it('names a priced item that has no target', () => {
    expect(lead([item(1, 1, 'a', null, '100.00'), item(2, 1, 'b', '12.50', null)])).toEqual({
      kind: 'priced',
      name: 'b',
      amount: '$12.50',
    })
  })
})

describe('newlyStruck', () => {
  const items = [item(1, 1, 'a', '90.00', '100.00'), item(2, 1, 'b', '50.00', '100.00'), item(3, 1, 'c', '200.00', '100.00')]

  it('reports nothing on the first load', () => {
    expect(newlyStruck(null, items)).toEqual([])
  })

  it('reports items in range now that were not before', () => {
    expect(newlyStruck(new Set([1]), items)).toEqual([2])
  })

  it('ignores items that were already in range or still are not', () => {
    expect(newlyStruck(new Set([1, 2]), items)).toEqual([])
  })
})
