import { describe, expect, it } from 'vitest'
import { siteIdsAfterToggle } from './siteIdsAfterToggle'

describe('siteIdsAfterToggle', () => {
  it('unticks a site from the ones searched', () => {
    expect(siteIdsAfterToggle([1, 2, 3], 2, 3)).toEqual({ siteIds: [1, 3] })
    expect(siteIdsAfterToggle([1, 3], 3, 3)).toEqual({ siteIds: [1] })
  })

  it('ticks a site, and stores every site picked as no restriction', () => {
    expect(siteIdsAfterToggle([1], 3, 3)).toEqual({ siteIds: [1, 3] })
    expect(siteIdsAfterToggle([1, 3], 2, 3)).toEqual({ siteIds: null })
  })

  it('refuses to untick the only site left', () => {
    expect(siteIdsAfterToggle([2], 2, 3)).toEqual({
      error: 'Keep at least one site. Snagr needs somewhere to look.',
    })
    expect(siteIdsAfterToggle([1], 1, 1)).toEqual({
      error: 'Keep at least one site. Snagr needs somewhere to look.',
    })
  })
})
