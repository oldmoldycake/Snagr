import { describe, expect, it } from 'vitest'
import type { Site } from '@/api/types'
import { defaultSiteName, findDuplicate, hostOf, isPlausibleUrl, normalizeBaseUrl } from './siteUrl'

function site(id: number, name: string, base_url: string): Site {
  return { id, name, base_url } as Site
}

describe('normalizeBaseUrl', () => {
  it('adds https:// when no scheme is given', () => {
    expect(normalizeBaseUrl('facebook.com/marketplace')).toBe('https://facebook.com/marketplace')
  })

  it('keeps a scheme that is already there', () => {
    expect(normalizeBaseUrl('http://ebay.com')).toBe('http://ebay.com')
    expect(normalizeBaseUrl('HTTPS://ebay.com')).toBe('HTTPS://ebay.com')
  })

  it('trims whitespace and drops trailing slashes', () => {
    expect(normalizeBaseUrl('  ebay.com/  ')).toBe('https://ebay.com')
    expect(normalizeBaseUrl('https://ebay.com///')).toBe('https://ebay.com')
  })

  it('leaves the path and its case alone', () => {
    expect(normalizeBaseUrl('Facebook.com/Marketplace/')).toBe('https://Facebook.com/Marketplace')
  })
})

describe('hostOf', () => {
  it('reads the host with or without a scheme', () => {
    expect(hostOf('https://ebay.com')).toBe('ebay.com')
    expect(hostOf('ebay.com')).toBe('ebay.com')
  })

  it('drops a leading www. and the path, and lowercases', () => {
    expect(hostOf('https://WWW.Newegg.com/p/123')).toBe('newegg.com')
  })

  it('keeps other subdomains', () => {
    expect(hostOf('shop.example.co.uk/deals')).toBe('shop.example.co.uk')
  })

  it('is null for something that is not a URL', () => {
    expect(hostOf('face book')).toBeNull()
    expect(hostOf('')).toBeNull()
  })
})

describe('isPlausibleUrl', () => {
  it('accepts a dotted host, with or without scheme, www. or path', () => {
    expect(isPlausibleUrl('facebook.com/marketplace')).toBe(true)
    expect(isPlausibleUrl('https://www.ebay.com/')).toBe(true)
    expect(isPlausibleUrl('KEH.com')).toBe(true)
  })

  it('refuses a host without a dot', () => {
    expect(isPlausibleUrl('ebay')).toBe(false)
    expect(isPlausibleUrl('https://localhost')).toBe(false)
  })

  it('refuses spaces, empty input and stray dots', () => {
    expect(isPlausibleUrl('face book.com')).toBe(false)
    expect(isPlausibleUrl('ebay.com/some path')).toBe(false)
    expect(isPlausibleUrl('   ')).toBe(false)
    expect(isPlausibleUrl('ebay.')).toBe(false)
    expect(isPlausibleUrl('.com')).toBe(false)
  })
})

describe('findDuplicate', () => {
  const sites = [site(1, 'ebay.com', 'https://www.ebay.com'), site(2, 'newegg.com', 'https://newegg.com/')]

  it('matches on host, ignoring scheme, www., path, trailing slashes and case', () => {
    expect(findDuplicate('EBAY.com/itm/1', sites)?.id).toBe(1)
    expect(findDuplicate('http://www.newegg.com', sites)?.id).toBe(2)
  })

  it('finds nothing for a new host or an unparseable address', () => {
    expect(findDuplicate('mercari.com', sites)).toBeUndefined()
    expect(findDuplicate('face book', sites)).toBeUndefined()
  })

  it('treats another subdomain as a different site', () => {
    expect(findDuplicate('pages.ebay.com', sites)).toBeUndefined()
  })
})

describe('defaultSiteName', () => {
  it('is the host', () => {
    expect(defaultSiteName('https://www.Facebook.com/marketplace/')).toBe('facebook.com')
  })

  it('is empty while the address does not parse', () => {
    expect(defaultSiteName('face book')).toBe('')
  })
})
