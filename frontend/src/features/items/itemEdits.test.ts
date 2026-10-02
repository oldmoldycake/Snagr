import { describe, expect, it } from 'vitest'
import { hasItemEdits, type ItemForm } from './itemEdits'

const opened: ItemForm = {
  name: 'Pokémon Sapphire (GBA)',
  target: '45.00',
  tracking: {
    criteria: 'authentic cartridge',
    selectionMode: 'best_match',
    maxListings: 5,
    recheckIntervalMinutes: null,
    hunt: true,
    siteIds: [1, 3],
  },
}

const withTracking = (tracking: Partial<ItemForm['tracking']>): ItemForm => ({
  ...opened,
  tracking: { ...opened.tracking, ...tracking },
})

describe('hasItemEdits', () => {
  it('sees nothing in an untouched form', () => {
    expect(hasItemEdits(opened, { ...opened })).toBe(false)
  })

  it('sees new text, but not spaces around the old', () => {
    expect(hasItemEdits(opened, { ...opened, name: 'Pokémon Ruby (GBA)' })).toBe(true)
    expect(hasItemEdits(opened, { ...opened, target: '' })).toBe(true)
    expect(hasItemEdits(opened, withTracking({ criteria: '' }))).toBe(true)
    expect(hasItemEdits(opened, { ...opened, name: ' Pokémon Sapphire (GBA) ', target: '45.00 ' })).toBe(false)
    expect(hasItemEdits(opened, withTracking({ criteria: 'authentic cartridge\n' }))).toBe(false)
  })

  it('sees any tracking option changed', () => {
    expect(hasItemEdits(opened, withTracking({ selectionMode: 'cheapest' }))).toBe(true)
    expect(hasItemEdits(opened, withTracking({ maxListings: 6 }))).toBe(true)
    expect(hasItemEdits(opened, withTracking({ recheckIntervalMinutes: 30 }))).toBe(true)
    expect(hasItemEdits(opened, withTracking({ hunt: false }))).toBe(true)
  })

  it('sees a different set of sites, but not the same set picked again', () => {
    expect(hasItemEdits(opened, withTracking({ siteIds: [1] }))).toBe(true)
    expect(hasItemEdits(opened, withTracking({ siteIds: null }))).toBe(true)
    expect(hasItemEdits(opened, withTracking({ siteIds: [3, 1] }))).toBe(false)
  })
})
