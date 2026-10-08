import { describe, expect, it } from 'vitest'
import { readCategoryFilters, withCategoryFilters } from './categoryFilters'

const read = (query: string, siteIds: number[] = [1, 2]) => readCategoryFilters(new URLSearchParams(query), siteIds)

describe('readCategoryFilters', () => {
  it('reads a bare URL as no filters', () => {
    expect(read('')).toEqual({ status: 'all', siteId: undefined, search: '' })
    expect(read('range=90d')).toEqual({ status: 'all', siteId: undefined, search: '' })
  })

  it('reads each filter from its param', () => {
    expect(read('status=snagged&site=2&search=x100')).toEqual({ status: 'snagged', siteId: 2, search: 'x100' })
    expect(read('status=no_listings').status).toBe('no_listings')
  })

  it('reads an unknown status as all', () => {
    expect(read('status=cheap').status).toBe('all')
  })

  it('drops a site filter the page offers no picker to clear', () => {
    expect(read('site=3').siteId).toBeUndefined()
    expect(read('site=ebay').siteId).toBeUndefined()
    expect(read('site=1', [1]).siteId).toBeUndefined()
    expect(read('site=1', []).siteId).toBeUndefined()
  })
})

describe('withCategoryFilters', () => {
  it('writes each filter and keeps the range', () => {
    const params = withCategoryFilters(new URLSearchParams('range=90d'), {
      status: 'above_target',
      siteId: 2,
      search: 'x100',
    })
    expect(params.toString()).toBe('range=90d&status=above_target&site=2&search=x100')
    expect(read(params.toString())).toEqual({ status: 'above_target', siteId: 2, search: 'x100' })
  })

  it('changes only the filters it is given', () => {
    const params = withCategoryFilters(new URLSearchParams('status=snagged&site=2'), { search: 'fuji' })
    expect(params.toString()).toBe('status=snagged&site=2&search=fuji')
  })

  it('drops a filter set back to its default', () => {
    const params = withCategoryFilters(new URLSearchParams('range=7d&status=snagged&site=2&search=x100'), {
      status: 'all',
      siteId: undefined,
      search: '',
    })
    expect(params.toString()).toBe('range=7d')
  })
})
