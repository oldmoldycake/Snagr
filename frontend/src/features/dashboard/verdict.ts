import type { ItemSummary } from '@/api/types'
import { effectiveTarget, sortByDistanceToTarget } from '@/features/items/WatchList'
import { toCents } from '@/lib/money'

/**
 * The items at target the verdict hero names, furthest under target first, and
 * how many it leaves to the shelves. Same prose rule as siteList: up to three
 * by name, past that two and "N more", so the line stays one sentence.
 */
export function namedHits(items: ItemSummary[]): { named: ItemSummary[]; more: number } {
  const hits = sortByDistanceToTarget(items.filter((item) => item.target_met))
  if (hits.length <= 3) return { named: hits, more: 0 }
  return { named: hits.slice(0, 2), more: hits.length - 2 }
}

/**
 * What the verdict hero says about the items not at target: the one closest
 * to its target, or why none can be measured against one. A target is
 * optional, so prices can arrive for items without one, and "no prices yet"
 * is then only true of the items that have one.
 */
export type Standing =
  | { kind: 'closest'; item: ItemSummary; gapCents: number }
  /** some item has a price, but no item has a target */
  | { kind: 'no_targets' }
  /** no item with a target has a price yet; `elsewhere` when an item without one does */
  | { kind: 'no_prices'; elsewhere: boolean }

/** The hero's standing, or null when every item with a price and a target is at target. */
export function standing(items: ItemSummary[]): Standing | null {
  let closest: { item: ItemSummary; gapCents: number; ratio: number } | null = null
  let priced = false
  let targeted = false
  for (const item of items) {
    const best = toCents(item.best_price)
    const target = toCents(effectiveTarget(item))
    if (best != null) priced = true
    if (target != null) targeted = true
    if (item.target_met || best == null || target == null || target <= 0) continue
    const gapCents = best - target
    const ratio = gapCents / target
    if (closest == null || ratio < closest.ratio) closest = { item, gapCents, ratio }
  }
  if (closest) return { kind: 'closest', item: closest.item, gapCents: closest.gapCents }
  if (items.some((item) => item.target_met)) return null
  if (priced && !targeted) return { kind: 'no_targets' }
  return { kind: 'no_prices', elsewhere: priced }
}
