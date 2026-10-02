import { describe, expect, it } from 'vitest'
import { seriesLabel, sharedTitlePrefix, titleDifference } from './listingTitles'

const GPU = [
  'RTX 4060 Ti 16GB (Renewed)',
  'RTX 4060 Ti 16GB',
  'RTX 4060 Ti 16GB (New)',
  'RTX 4060 Ti 16GB — Used, Good',
]

describe('sharedTitlePrefix', () => {
  it('finds the words every title starts with', () => {
    expect(sharedTitlePrefix(GPU)).toBe('RTX 4060 Ti 16GB')
  })

  it('stops at a word boundary', () => {
    expect(sharedTitlePrefix(['Arc B580 Steel Legend', 'Arc B580 Stealth'])).toBe('Arc B580 ')
  })

  it('ignores unknown titles, and needs two known ones', () => {
    expect(sharedTitlePrefix([null, 'RTX 4060 Ti 16GB (New)', 'RTX 4060 Ti 16GB'])).toBe('RTX 4060 Ti 16GB')
    expect(sharedTitlePrefix([null, 'RTX 4060 Ti 16GB (New)'])).toBe('')
    expect(sharedTitlePrefix([])).toBe('')
  })

  it('is empty when the titles share no word', () => {
    expect(sharedTitlePrefix(['Nintendo GameCube Controller', 'GameCube Controller (Official Nintendo)'])).toBe('')
  })
})

describe('titleDifference', () => {
  const prefix = sharedTitlePrefix(GPU)

  it('keeps what the shared prefix leaves, unwrapped from its brackets', () => {
    expect(titleDifference('RTX 4060 Ti 16GB (Renewed)', prefix)).toBe('Renewed')
  })

  it('drops the separator left at the cut', () => {
    expect(titleDifference('RTX 4060 Ti 16GB — Used, Good', prefix)).toBe('Used, Good')
    expect(titleDifference('RTX 4060 Ti 16GB - Open Box', prefix)).toBe('Open Box')
  })

  it('keeps brackets that only open the difference', () => {
    expect(titleDifference('Pokemon Emerald (GBA) Authentic', 'Pokemon Emerald ')).toBe('(GBA) Authentic')
  })

  it('is empty when nothing sets the title apart, or it is unknown', () => {
    expect(titleDifference('RTX 4060 Ti 16GB', prefix)).toBe('')
    expect(titleDifference(null, prefix)).toBe('')
  })

  it('keeps the whole title when nothing is shared', () => {
    expect(titleDifference('Nintendo GameCube Controller OEM', '')).toBe('Nintendo GameCube Controller OEM')
  })
})

describe('seriesLabel', () => {
  const prefix = sharedTitlePrefix(GPU)

  it('reads site first, then the difference, like the listing row', () => {
    expect(seriesLabel('amazon.com', 'RTX 4060 Ti 16GB (New)', prefix)).toBe('amazon.com · New')
    expect(seriesLabel('ebay.com', 'RTX 4060 Ti 16GB — Used, Good', prefix)).toBe('ebay.com · Used, Good')
  })

  it('is the site alone when the title sets nothing apart', () => {
    expect(seriesLabel('newegg.com', 'RTX 4060 Ti 16GB', prefix)).toBe('newegg.com')
    expect(seriesLabel('newegg.com', null, prefix)).toBe('newegg.com')
  })

  it('cuts a long difference short, never the site', () => {
    expect(seriesLabel('ebay.com', 'Nintendo GameCube Controller Official OEM Indigo', '')).toBe(
      'ebay.com · Nintendo GameCube Control…',
    )
  })
})
