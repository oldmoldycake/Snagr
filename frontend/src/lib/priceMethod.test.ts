import { describe, expect, it } from 'vitest'
import { priceMethodLabel } from './priceMethod'

describe('priceMethodLabel', () => {
  it('tags nothing when the model read the price, or nobody recorded how', () => {
    expect(priceMethodLabel('llm')).toBeNull()
    expect(priceMethodLabel(null)).toBeNull()
    expect(priceMethodLabel(undefined)).toBeNull()
  })

  it('folds the three structured-data readers into one plain tag', () => {
    expect(priceMethodLabel('jsonld')).toBe('page data')
    expect(priceMethodLabel('meta')).toBe('page data')
    expect(priceMethodLabel('microdata')).toBe('page data')
  })

  it('names a replayed locator', () => {
    expect(priceMethodLabel('locator')).toBe('learned spot')
  })

  it('shows a code it does not know rather than hiding it', () => {
    expect(priceMethodLabel('ocr')).toBe('ocr')
  })
})
