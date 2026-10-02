import { describe, expect, it } from 'vitest'
import { hasCategoryEdits } from './categoryEdits'

const keyboards = { name: 'Keyboards', site_ids: [1, 3] }

describe('hasCategoryEdits', () => {
  it('sees nothing in an untouched dialog', () => {
    expect(hasCategoryEdits(keyboards, 'Keyboards', null)).toBe(false)
  })

  it('sees a new name, but not spaces around the old one', () => {
    expect(hasCategoryEdits(keyboards, 'Mechanical keyboards', null)).toBe(true)
    expect(hasCategoryEdits(keyboards, '', null)).toBe(true)
    expect(hasCategoryEdits(keyboards, ' Keyboards ', null)).toBe(false)
  })

  it('sees a different set of sites, but not the same set picked again', () => {
    expect(hasCategoryEdits(keyboards, 'Keyboards', [1])).toBe(true)
    expect(hasCategoryEdits(keyboards, 'Keyboards', [1, 3, 4])).toBe(true)
    expect(hasCategoryEdits(keyboards, 'Keyboards', [])).toBe(true)
    expect(hasCategoryEdits(keyboards, 'Keyboards', [3, 1])).toBe(false)
  })

  it('sees nothing in a picker left empty on a category with no sites', () => {
    expect(hasCategoryEdits({ name: 'Lenses', site_ids: [] }, 'Lenses', [])).toBe(false)
  })
})
