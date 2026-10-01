import { listItems } from '@/api/endpoints'
import type { ItemListParams, ItemSummary, Paginated } from '@/api/types'

/** Big enough that a typical self-hosted watch list arrives in one request. */
export const ALL_ITEMS_PAGE_SIZE = 200

/**
 * Every watched item matching `params`, fetched page by page until `total`
 * is reached. The pages that list items sort and group them client-side
 * (distance to target, category shelves), so a single page would quietly
 * drop whatever sorted past it rather than whatever came last.
 *
 * The result keeps the Paginated shape, as one page holding everything, so
 * readers of the items cache see the same envelope as any other list.
 */
export async function listAllItems(
  params: Omit<ItemListParams, 'page' | 'per_page'> = {},
): Promise<Paginated<ItemSummary>> {
  const per_page = ALL_ITEMS_PAGE_SIZE
  const first = await listItems({ ...params, page: 1, per_page })
  const pages = Math.ceil(first.meta.total / per_page)
  const rest = await Promise.all(
    Array.from({ length: Math.max(0, pages - 1) }, (_, i) => listItems({ ...params, page: i + 2, per_page })),
  )
  // an item added or removed between requests shifts the pages, so one can
  // arrive twice; keep the first copy
  const byId = new Map<number, ItemSummary>()
  for (const item of [first, ...rest].flatMap((page) => page.data)) {
    if (!byId.has(item.id)) byId.set(item.id, item)
  }
  const data = [...byId.values()]
  return { data, meta: { page: 1, per_page: Math.max(1, data.length), total: data.length } }
}
