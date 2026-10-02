import type { ItemSummary } from '@/api/types'
import { sortByDistanceToTarget } from '@/features/items/WatchList'

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
