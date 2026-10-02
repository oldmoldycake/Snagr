import type { Listing, SelectionMode } from '@/api/types'

/** Best-match mode folds listings scoring under this. */
export const FOLD_SCORE = 70

export interface ListingFold {
  /** the rows on show, cheapest (or best match) first */
  main: Listing[]
  /** everything in the fold: the low-match tail first, then the rest */
  folded: Listing[]
  /** of the fold, the tracked listings folded for a low match score */
  lowMatch: Listing[]
  /** of the fold, the untracked, sold and ended listings */
  inactive: Listing[]
}

/**
 * Which listings show and which wait in the "N more" fold. Untracked, sold and
 * ended listings fold, and so, in best-match mode, does the low-scoring tail —
 * but never the whole list. `placed` pins a row to the side it was on when its
 * tracking was switched here (true = on show), so the switch never sends the
 * row the person is looking at out of sight.
 */
export function foldListings(
  listings: Listing[],
  mode: SelectionMode,
  placed: ReadonlyMap<number, boolean>,
): ListingFold {
  const byMode = (a: Listing, b: Listing) => {
    const priceDiff = Number(a.latest_price ?? Infinity) - Number(b.latest_price ?? Infinity)
    if (mode !== 'best_match') return priceDiff
    return (b.match_score ?? -1) - (a.match_score ?? -1) || priceDiff
  }
  const sorted = [...listings].sort(byMode)
  const active = sorted.filter((l) => l.active)

  const cleared = active.filter((l) => (l.match_score ?? -1) >= FOLD_SCORE)
  const foldLow = mode === 'best_match' && cleared.length > 0 && cleared.length < active.length
  const shown = (l: Listing) =>
    placed.get(l.id) ?? (l.active && (!foldLow || (l.match_score ?? -1) >= FOLD_SCORE))

  const lowMatch = active.filter((l) => !shown(l) && !placed.has(l.id))
  const inactive = sorted.filter((l) => !l.active && !shown(l))
  // tracked again from inside the fold: it stays there, among neither group
  const retracked = active.filter((l) => !shown(l) && placed.has(l.id))
  return { main: sorted.filter(shown), folded: [...lowMatch, ...retracked, ...inactive], lowMatch, inactive }
}
