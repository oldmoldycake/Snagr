import type { PageMeta } from '@/api/types'

/**
 * The page the review queue should show: `page` itself, unless it lies past
 * the last one — confirming or discarding the only photo on a later page
 * leaves earlier pages full, so the view steps back to them.
 */
export function pageInRange(page: number, meta: PageMeta): number {
  return Math.min(page, Math.max(1, Math.ceil(meta.total / meta.per_page)))
}
