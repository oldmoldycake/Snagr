import { describe, expect, it } from 'vitest'
import { zoomScroll } from './zoom'

describe('zoomScroll', () => {
  it('keeps the clicked spot under the pointer', () => {
    // a 3× zoom moves the spot at (100, 40) to (300, 120); scrolling by
    // (200, 80) puts it back at (100, 40) in the frame
    expect(zoomScroll({ x: 100, y: 40 }, 3)).toEqual({ left: 200, top: 80 })
  })

  it('does not scroll for a click in the top-left corner', () => {
    expect(zoomScroll({ x: 0, y: 0 }, 3)).toEqual({ left: 0, top: 0 })
  })

  it('does not scroll when nothing zooms', () => {
    expect(zoomScroll({ x: 120, y: 90 }, 1)).toEqual({ left: 0, top: 0 })
  })
})
