import type { TrackingValue } from './TrackingFields'

/** The add and edit item form: the name and target price as typed, and the tracking options. */
export interface ItemForm {
  name: string
  target: string
  tracking: TrackingValue
}

/**
 * Whether the item form holds something closing it would throw away: text
 * that differs from what it opened with once trimmed, or any tracking option
 * changed. Sites compare as a set, so a site ticked off and on again is no edit.
 */
export function hasItemEdits(opened: ItemForm, current: ItemForm): boolean {
  const from = opened.tracking
  const to = current.tracking
  return (
    current.name.trim() !== opened.name.trim() ||
    current.target.trim() !== opened.target.trim() ||
    to.criteria.trim() !== from.criteria.trim() ||
    to.selectionMode !== from.selectionMode ||
    to.maxListings !== from.maxListings ||
    to.recheckIntervalMinutes !== from.recheckIntervalMinutes ||
    to.hunt !== from.hunt ||
    siteSet(to.siteIds) !== siteSet(from.siteIds)
  )
}

/** A site selection as text, in id order; null (every site) is never equal to a list. */
function siteSet(ids: number[] | null): string {
  return ids == null ? 'all' : [...ids].sort((a, b) => a - b).join()
}
