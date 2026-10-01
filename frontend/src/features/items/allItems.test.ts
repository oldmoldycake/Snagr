import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ItemSummary } from '@/api/types'
import { ALL_ITEMS_PAGE_SIZE, listAllItems } from './allItems'

const item = (id: number) => ({ id }) as ItemSummary

/** Stubs fetch to serve `pages[n - 1]` for ?page=n, each with `total`. */
function stubPages(pages: ItemSummary[][], total: number) {
  const fetchMock = vi.fn(async (input: string) => {
    const url = new URL(input, 'http://snagr.test')
    const page = Number(url.searchParams.get('page'))
    const per_page = Number(url.searchParams.get('per_page'))
    return Response.json({ data: pages[page - 1] ?? [], meta: { page, per_page, total } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const pageParams = (fetchMock: ReturnType<typeof stubPages>) =>
  fetchMock.mock.calls.map((call) => new URL(String(call[0]), 'http://snagr.test').searchParams.get('page'))

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('listAllItems', () => {
  it('stops at one request when everything fits', async () => {
    const fetchMock = stubPages([[item(1), item(2)]], 2)

    const result = await listAllItems({ range: '30d' })
    expect(result.data.map((i) => i.id)).toEqual([1, 2])
    expect(result.meta.total).toBe(2)
    expect(pageParams(fetchMock)).toEqual(['1'])
  })

  it('fetches every page past the first', async () => {
    const full = Array.from({ length: ALL_ITEMS_PAGE_SIZE }, (_, i) => item(i + 1))
    const fetchMock = stubPages([full, [item(ALL_ITEMS_PAGE_SIZE + 1)]], ALL_ITEMS_PAGE_SIZE + 1)

    const result = await listAllItems({ category_id: 3 })
    expect(result.data).toHaveLength(ALL_ITEMS_PAGE_SIZE + 1)
    expect(result.meta.total).toBe(ALL_ITEMS_PAGE_SIZE + 1)
    expect(pageParams(fetchMock)).toEqual(['1', '2'])
    expect(String(fetchMock.mock.calls[1][0])).toContain('category_id=3')
  })

  it('keeps one copy of an item that a shifted page repeats', async () => {
    const full = Array.from({ length: ALL_ITEMS_PAGE_SIZE }, (_, i) => item(i + 1))
    stubPages([full, [item(ALL_ITEMS_PAGE_SIZE), item(ALL_ITEMS_PAGE_SIZE + 1)]], ALL_ITEMS_PAGE_SIZE + 2)

    const result = await listAllItems()
    expect(result.data).toHaveLength(ALL_ITEMS_PAGE_SIZE + 1)
    expect(new Set(result.data.map((i) => i.id)).size).toBe(ALL_ITEMS_PAGE_SIZE + 1)
  })

  it('returns an empty list without a second request', async () => {
    const fetchMock = stubPages([[]], 0)

    const result = await listAllItems()
    expect(result.data).toEqual([])
    expect(pageParams(fetchMock)).toEqual(['1'])
  })
})
