import type { ItemStatusFilter } from '@/api/types'

export const STATUS_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'snagged', label: 'At target' },
  { value: 'above_target', label: 'Above target' },
  { value: 'no_listings', label: 'No listings' },
] as const satisfies readonly { value: ItemStatusFilter; label: string }[]

/**
 * A category page's filters. They live in the URL beside ?range
 * (?status=snagged&site=3&search=x100), so Back from an item, a reload or a
 * shared link shows the same list.
 */
export interface CategoryFilters {
  status: ItemStatusFilter
  /** only items with a tracked listing on this site */
  siteId: number | undefined
  search: string
}

/**
 * The filters `params` asks for; anything unrecognized reads as no filter. So
 * does a site that isn't one of the category's sites, or the category's only
 * one: the page shows the site picker only for two or more, and a filter it
 * doesn't show couldn't be cleared.
 */
export function readCategoryFilters(params: URLSearchParams, siteIds: readonly number[]): CategoryFilters {
  const siteId = Number(params.get('site'))
  return {
    status: STATUS_FILTERS.find((f) => f.value === params.get('status'))?.value ?? 'all',
    siteId: siteIds.length > 1 && siteIds.includes(siteId) ? siteId : undefined,
    search: params.get('search') ?? '',
  }
}

/**
 * `params` with `change` applied. A filter set back to its default leaves the
 * URL, so a plain link to a category opens it unfiltered.
 */
export function withCategoryFilters(params: URLSearchParams, change: Partial<CategoryFilters>): URLSearchParams {
  const next = new URLSearchParams(params)
  const put = (name: string, value: string | undefined) => {
    if (value) next.set(name, value)
    else next.delete(name)
  }
  if ('status' in change) put('status', change.status === 'all' ? undefined : change.status)
  if ('siteId' in change) put('site', change.siteId?.toString())
  if ('search' in change) put('search', change.search)
  return next
}
