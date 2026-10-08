import type { QueryKey } from '@tanstack/react-query'
import type { Category, ItemDetail, ItemSummary, JobCreateRequest, Paginated } from '@/api/types'

/**
 * Which category each item the client has already fetched belongs to, read
 * off the items cache (`qk.items(...)` pages and `qk.item(id)` details). A
 * job carries its item but not its category, and there is no endpoint that
 * maps one to the other; an item this tab has never listed is simply absent,
 * and a hunt for it then does not count as live in any category.
 */
export function itemCategories(cached: [QueryKey, unknown][]): Map<number, number> {
  const categories = new Map<number, number>()
  for (const [key, data] of cached) {
    if (data == null || key[0] !== 'items') continue
    if (key[1] === 'list') {
      for (const item of (data as Paginated<ItemSummary>).data) {
        categories.set(item.id, item.category_id)
      }
    } else if (key[1] === 'detail' && key.length === 3) {
      const item = data as ItemDetail
      categories.set(item.id, item.category_id)
    }
  }
  return categories
}

/**
 * How many hunts pressing Hunt for `target` would ask for, before asking: one
 * per (item, site) pair, where an item searches its own sites or else every
 * site its category is linked to — the fan-out the backend's enqueue does.
 * `items` is every item the caller watches.
 */
export function plannedHunts(
  target: Omit<JobCreateRequest, 'kind'>,
  items: ItemSummary[],
  categories: Category[],
): number {
  const { scope, scope_id } = target
  let hunts = 0
  for (const item of items) {
    if (scope === 'item' && item.id !== scope_id) continue
    if (scope === 'category' && item.category_id !== scope_id) continue
    const sites = item.site_ids ?? categories.find((c) => c.id === item.category_id)?.site_ids ?? []
    hunts += scope === 'site' ? Number(sites.includes(scope_id!)) : sites.length
  }
  return hunts
}
