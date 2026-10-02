import { describe, expect, it } from 'vitest'
import { MAX_REFERENCE_BYTES, referenceFileError } from './upload'

describe('referenceFileError', () => {
  it('accepts a photo up to the 10 MB limit', () => {
    expect(referenceFileError({ size: 2_000_000 })).toBeNull()
    expect(referenceFileError({ size: MAX_REFERENCE_BYTES })).toBeNull()
  })

  it('refuses a photo over it, in the backend\'s words', () => {
    expect(referenceFileError({ size: MAX_REFERENCE_BYTES + 1 })).toBe('Must be 10 MB or smaller')
  })
})
