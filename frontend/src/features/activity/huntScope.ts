import type { QueryKey } from '@tanstack/react-query'
import type { ItemDetail, ItemSummary, Paginated } from '@/api/types'

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
