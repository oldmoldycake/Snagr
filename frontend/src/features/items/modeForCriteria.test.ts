import { describe, expect, it } from 'vitest'
import { modeForCriteria } from './modeForCriteria'

const cheapest = { mode: 'cheapest', switched: false } as const
const switched = { mode: 'best_match', switched: true } as const

describe('modeForCriteria', () => {
  it('switches Cheapest to Best match when criteria are typed into an empty field', () => {
    expect(modeForCriteria(cheapest, '', 'd')).toEqual(switched)
  })

  it('switches back when the criteria it switched for are cleared', () => {
    expect(modeForCriteria(switched, 'dry battery', 'dry')).toEqual(switched)
    expect(modeForCriteria(switched, 'd', ' ')).toEqual(cheapest)
  })

  it('leaves criteria that were already there to the mode they have', () => {
    expect(modeForCriteria(cheapest, 'boxed', 'boxed, manual')).toEqual(cheapest)
    expect(modeForCriteria(cheapest, 'boxed', '')).toEqual(cheapest)
  })

  it('never switches a Best match it did not switch to', () => {
    const chosen = { mode: 'best_match', switched: false } as const
    expect(modeForCriteria(chosen, '', 'boxed')).toEqual(chosen)
    expect(modeForCriteria(chosen, 'boxed', '')).toEqual(chosen)
  })
})
