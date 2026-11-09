import type { Category, User } from '@/api/types'

/**
 * Whether `user` may rename `category` and choose its sites: an admin, or whoever
 * created it — the backend's rule, which answers anyone else 403. Either change
 * reaches everyone with items in the category. Deleting one stays an admin's.
 */
export function canEditCategory(
  category: Pick<Category, 'created_by'>,
  user: Pick<User, 'id' | 'role'> | undefined,
): boolean {
  if (!user) return false
  return user.role === 'admin' || category.created_by === user.id
}

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
