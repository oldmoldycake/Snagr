import { describe, expect, it } from 'vitest'
import type { Listing } from '@/api/types'
import { foldListings } from './listingFold'

function listing(id: number, price: string, active = true, match: number | null = null): Listing {
  return { id, latest_price: price, active, match_score: match } as Listing
}

const ids = (listings: Listing[]) => listings.map((l) => l.id)
const none = new Map<number, boolean>()

describe('foldListings', () => {
  it('shows tracked listings cheapest first and folds the untracked', () => {
    const fold = foldListings([listing(1, '30.00'), listing(2, '10.00', false), listing(3, '20.00')], 'cheapest', none)
    expect(ids(fold.main)).toEqual([3, 1])
    expect(ids(fold.folded)).toEqual([2])
    expect(ids(fold.inactive)).toEqual([2])
  })

  it('folds the low-match tail in best-match mode, ahead of the untracked', () => {
    const fold = foldListings(
      [listing(1, '10.00', true, 40), listing(2, '20.00', true, 90), listing(3, '5.00', false, 95)],
      'best_match',
      none,
    )
    expect(ids(fold.main)).toEqual([2])
    expect(ids(fold.lowMatch)).toEqual([1])
    expect(ids(fold.folded)).toEqual([1, 3])
  })

  it('never folds the whole list for a low match', () => {
    const fold = foldListings([listing(1, '10.00', true, 40), listing(2, '20.00', true, 50)], 'best_match', none)
    expect(ids(fold.main)).toEqual([2, 1])
    expect(fold.folded).toEqual([])
  })

  it('keeps a listing untracked here where it was, in its place', () => {
    const fold = foldListings(
      [listing(1, '10.00'), listing(2, '20.00', false), listing(3, '30.00')],
      'cheapest',
      new Map([[2, true]]),
    )
    expect(ids(fold.main)).toEqual([1, 2, 3])
    expect(fold.folded).toEqual([])
  })

  it('keeps a listing tracked again from the fold in the fold, counted in neither group', () => {
    const fold = foldListings(
      [listing(1, '10.00'), listing(2, '20.00', true, 90), listing(3, '30.00', false)],
      'cheapest',
      new Map([[2, false]]),
    )
    expect(ids(fold.main)).toEqual([1])
    expect(ids(fold.folded)).toEqual([2, 3])
    expect(fold.lowMatch).toEqual([])
    expect(ids(fold.inactive)).toEqual([3])
  })
})
