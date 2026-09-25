import { describe, expect, it } from 'vitest'
import { siteList } from './siteList'

describe('siteList', () => {
  it('reads as prose up to three names', () => {
    expect(siteList([])).toBe('')
    expect(siteList(['eBay'])).toBe('eBay')
    expect(siteList(['eBay', 'Amazon'])).toBe('eBay and Amazon')
    expect(siteList(['eBay', 'Newegg', 'Amazon'])).toBe('eBay, Newegg and Amazon')
  })

  it('names two and counts the rest beyond three', () => {
    expect(siteList(['eBay', 'Newegg', 'Amazon', 'KEH', 'Mercari'])).toBe('eBay, Newegg and 3 more')
  })
})
