import type { Category } from '@/api/types'

/**
 * Whether Edit category holds something a save would change: a name that differs
 * once trimmed, or a picked set of sites other than the linked ones, in any
 * order. An untouched picker (`null`) changes nothing.
 */
export function hasCategoryEdits(
  category: Pick<Category, 'name' | 'site_ids'>,
  name: string,
  pickedSiteIds: number[] | null,
): boolean {
  if (name.trim() !== category.name) return true
  if (!pickedSiteIds) return false
  return [...pickedSiteIds].sort().join() !== [...category.site_ids].sort().join()
}
