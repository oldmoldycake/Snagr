/**
 * The dashboard's shelves as data: which categories get a shelf, in what order,
 * which start open, and what a collapsed shelf says in its one line. No React
 * here, so every rule is pinned down in shelves.test.ts.
 */
import type { Category, ItemSummary } from '@/api/types'
import { effectiveTarget, sortByDistanceToTarget } from '@/features/items/WatchList'
import { formatMoney, fromCents, toCents } from '@/lib/money'

/** What a collapsed shelf shows in place of its rows. Amounts are formatted money. */
export type Lead =
  | { kind: 'hit'; name: string; amount: string }
  | { kind: 'closest'; name: string; amount: string }
  | { kind: 'priced'; name: string; amount: string }
  | { kind: 'idle' }

/** A category holding at least one of the caller's items. */
export interface Shelf {
  category: Category
  /** closest to target first */
  items: ItemSummary[]
  /** how many of its items are in range */
  hits: number
  lead: Lead
}

/** One browser's remembered state for a shelf: collapsed or not, and how many hits it had then. */
export interface StoredShelf {
  collapsed: boolean
  snaggedAt: number
}

/** How far over target the item's best price is, as a fraction of the target; null without both. */
function distance(item: ItemSummary): { gapCents: number; ratio: number } | null {
  const best = toCents(item.best_price)
  const target = toCents(effectiveTarget(item))
  if (best == null || target == null || target <= 0) return null
  return { gapCents: best - target, ratio: (best - target) / target }
}

/** The shelf's closest priced item that isn't in range yet, if any. */
function closestItem(items: ItemSummary[]): { item: ItemSummary; gapCents: number; ratio: number } | null {
  let closest: { item: ItemSummary; gapCents: number; ratio: number } | null = null
  for (const item of items) {
    if (item.target_met) continue
    const d = distance(item)
    if (d && (closest == null || d.ratio < closest.ratio)) closest = { item, ...d }
  }
  return closest
}

/** The one line a collapsed shelf shows: its first strike, else its closest item, else that it's still hunting. */
export function lead(items: ItemSummary[]): Lead {
  const sorted = sortByDistanceToTarget(items)
  const hit = sorted.find((item) => item.target_met)
  if (hit) return { kind: 'hit', name: hit.name, amount: formatMoney(hit.best_price, hit.currency) }
  const closest = closestItem(sorted)
  if (closest) {
    return {
      kind: 'closest',
      name: closest.item.name,
      amount: formatMoney(fromCents(closest.gapCents), closest.item.currency),
    }
  }
  // a price without a target has no distance to report, but it is still a price
  const priced = sorted.find((item) => item.best_price != null)
  if (priced) return { kind: 'priced', name: priced.name, amount: formatMoney(priced.best_price, priced.currency) }
  return { kind: 'idle' }
}

/**
 * Most urgent first: shelves that hold items but have no sites to search them,
 * then shelves with strikes (more first), then by the closest item's distance
 * to target, then shelves with no prices yet; ties go alphabetically.
 */
export function orderShelves(shelves: Shelf[]): Shelf[] {
  const rank = (shelf: Shelf): [number, number] => {
    if (shelf.category.site_ids.length === 0) return [0, 0]
    if (shelf.hits > 0) return [1, -shelf.hits]
    const closest = closestItem(shelf.items)
    if (closest) return [2, closest.ratio]
    return [3, 0]
  }
  return [...shelves].sort((a, b) => {
    const [ta, va] = rank(a)
    const [tb, vb] = rank(b)
    return ta - tb || va - vb || a.category.name.localeCompare(b.category.name)
  })
}

/**
 * Splits categories into shelves (holding at least one of the caller's items)
 * and one-line rows (holding none). Counts come from the caller's items, never
 * from Category.item_count, which counts every user's items on the instance.
 */
export function groupShelves(
  items: ItemSummary[],
  categories: Category[],
  justCreatedId: number | null = null,
): { shelves: Shelf[]; rows: Category[] } {
  const byCategory = new Map<number, ItemSummary[]>()
  for (const item of items) {
    const list = byCategory.get(item.category_id)
    if (list) list.push(item)
    else byCategory.set(item.category_id, [item])
  }

  const shelves: Shelf[] = []
  const rows: Category[] = []
  for (const category of categories) {
    const own = byCategory.get(category.id)
    if (!own) {
      rows.push(category)
      continue
    }
    const sorted = sortByDistanceToTarget(own)
    shelves.push({
      category,
      items: sorted,
      hits: sorted.filter((item) => item.target_met).length,
      lead: lead(sorted),
    })
  }

  rows.sort((a, b) => {
    if (a.id === justCreatedId) return -1
    if (b.id === justCreatedId) return 1
    return a.name.localeCompare(b.name)
  })
  return { shelves: orderShelves(shelves), rows }
}

/**
 * Category ids that start open when this browser remembers nothing: every
 * shelf when there are four or fewer, otherwise the ones with strikes plus the
 * one holding the single closest priced item.
 */
export function defaultOpen(shelves: Shelf[]): Set<number> {
  if (shelves.length <= 4) return new Set(shelves.map((shelf) => shelf.category.id))
  const open = new Set(shelves.filter((shelf) => shelf.hits > 0).map((shelf) => shelf.category.id))
  let closest: { id: number; ratio: number } | null = null
  for (const shelf of shelves) {
    const item = closestItem(shelf.items)
    if (item && (closest == null || item.ratio < closest.ratio)) closest = { id: shelf.category.id, ratio: item.ratio }
  }
  if (closest) open.add(closest.id)
  return open
}

/**
 * Whether a shelf is open. A stored collapse loses to a new strike: when the
 * shelf has more hits than it had when collapsed, it opens and `reopened` tells
 * the caller to store it as open, so collapsing can never hide a strike.
 */
export function resolveOpen(
  stored: StoredShelf | undefined,
  shelf: Shelf,
  defaults: Set<number>,
): { open: boolean; reopened: boolean } {
  if (stored == null) return { open: defaults.has(shelf.category.id), reopened: false }
  if (stored.collapsed && shelf.hits > stored.snaggedAt) return { open: true, reopened: true }
  return { open: !stored.collapsed, reopened: false }
}

/**
 * Items in range now that weren't in the previous response. With no previous
 * response (the first load) nothing counts as new: those strikes are old news.
 */
export function newlyStruck(previousInRangeIds: Set<number> | null, items: ItemSummary[]): number[] {
  if (previousInRangeIds == null) return []
  return items.filter((item) => item.target_met && !previousInRangeIds.has(item.id)).map((item) => item.id)
}
