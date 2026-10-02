import { describe, expect, it } from 'vitest'
import { ladderLabelJoins } from './ladderLabels'

const HIGH = '30d high $601.66'

describe('ladderLabelJoins', () => {
  it('keeps ⌖ at its notch when it clears both neighbours', () => {
    expect(ladderLabelJoins(54, 'end', '⌖ $58.00 ·', '7d high $61.66', 'now $55.00 ⌖', 360)).toBe(false)
  })

  it('joins "now" past 55%, measured or not', () => {
    expect(ladderLabelJoins(60, 'end', '⌖ $556.00 ·', HIGH, 'now $540.00 ⌖', 360)).toBe(true)
    expect(ladderLabelJoins(60, 'end', '⌖ $556.00 ·', HIGH, 'now $540.00 ⌖', 0)).toBe(true)
  })

  it('joins "now" rather than print over the high label', () => {
    expect(ladderLabelJoins(50, 'end', '⌖ $580.00 ·', HIGH, 'now $560.00 ⌖', 360)).toBe(true)
    expect(ladderLabelJoins(42, 'end', '⌖ $99,999,999.99 ·', HIGH, 'now $560.00 ⌖', 360)).toBe(true)
  })

  it('keeps "now" on its marker when it clears both neighbours', () => {
    expect(ladderLabelJoins(46, 'center', 'now $580.00', HIGH, '⌖ target $550.00', 360)).toBe(false)
  })

  it('joins "⌖ target" rather than print "now" over either neighbour on a phone-width row', () => {
    expect(ladderLabelJoins(50, 'center', 'now $1,200.00', '30d high $1,400.00', '⌖ target $1,000.00', 342)).toBe(
      true,
    )
    expect(ladderLabelJoins(55, 'center', 'now $1,200.00', '7d high $1,250.00', '⌖ target $1,000.00', 342)).toBe(
      true,
    )
  })

  it('stays put before the row is measured', () => {
    expect(ladderLabelJoins(42, 'end', '⌖ $99,999,999.99 ·', HIGH, 'now $560.00 ⌖', 0)).toBe(false)
    expect(ladderLabelJoins(50, 'center', 'now $1,200.00', HIGH, '⌖ target $1,000.00', 0)).toBe(false)
  })
})
