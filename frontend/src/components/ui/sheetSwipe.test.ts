import { describe, expect, it } from 'vitest'
import { swipeCloses } from './sheetSwipe'

describe('swipeCloses', () => {
  it('closes once the sheet is pulled down a quarter of its height, however slowly', () => {
    expect(swipeCloses(150, 1200, 600)).toBe(true)
    expect(swipeCloses(149, 1200, 600)).toBe(false)
    expect(swipeCloses(50, 2000, 200)).toBe(true)
  })

  it('closes on a flick down that falls short of a quarter', () => {
    expect(swipeCloses(60, 80, 600)).toBe(true)
    expect(swipeCloses(60, 600, 600)).toBe(false)
  })

  it('springs back from a tap that wobbles, however fast', () => {
    expect(swipeCloses(0, 90, 600)).toBe(false)
    expect(swipeCloses(8, 5, 600)).toBe(false)
  })

  it('springs back when let go level with or above the press', () => {
    expect(swipeCloses(-200, 100, 600)).toBe(false)
    expect(swipeCloses(0, 0, 0)).toBe(false)
  })
})
