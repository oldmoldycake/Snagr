import { describe, expect, it } from 'vitest'
import { pageInRange } from './queue'

describe('pageInRange', () => {
  it('steps back to the last page that still has photos', () => {
    expect(pageInRange(3, { page: 3, per_page: 24, total: 48 })).toBe(2)
    expect(pageInRange(5, { page: 5, per_page: 24, total: 25 })).toBe(2)
  })

  it('lands on the first page once the queue is empty', () => {
    expect(pageInRange(2, { page: 2, per_page: 24, total: 0 })).toBe(1)
  })

  it('leaves a page that still has photos alone', () => {
    expect(pageInRange(2, { page: 2, per_page: 24, total: 49 })).toBe(2)
    expect(pageInRange(1, { page: 1, per_page: 24, total: 0 })).toBe(1)
  })
})
