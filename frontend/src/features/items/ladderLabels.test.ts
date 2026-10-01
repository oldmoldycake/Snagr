import { describe, expect, it } from 'vitest'
import { ladderTargetJoinsNow } from './ladderLabels'

const HIGH = '30d high $601.66'

describe('ladderTargetJoinsNow', () => {
  it('keeps ⌖ at its notch when it clears the high label', () => {
    expect(ladderTargetJoinsNow(50, '⌖ $580.00 ·', HIGH, 360)).toBe(false)
  })

  it('joins "now" past 55%, measured or not', () => {
    expect(ladderTargetJoinsNow(60, '⌖ $556.00 ·', HIGH, 360)).toBe(true)
    expect(ladderTargetJoinsNow(60, '⌖ $556.00 ·', HIGH, 0)).toBe(true)
  })

  it('joins "now" rather than print over the high label', () => {
    expect(ladderTargetJoinsNow(0, '⌖ $99,999,999.99 ·', HIGH, 360)).toBe(true)
    expect(ladderTargetJoinsNow(1, '⌖ $600.00 ·', HIGH, 360)).toBe(true)
  })

  it('stays at its notch before the row is measured', () => {
    expect(ladderTargetJoinsNow(0, '⌖ $99,999,999.99 ·', HIGH, 0)).toBe(false)
  })
})
