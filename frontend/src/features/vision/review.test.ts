import { describe, expect, it } from 'vitest'
import { suggestionText } from './review'

describe('suggestionText', () => {
  it('states the confidence as a whole percentage of the suggested side', () => {
    expect(suggestionText('real', '0.88')).toBe('likely real · 88%')
    expect(suggestionText('fake', '0.66')).toBe('likely fake · 66%')
  })

  it('keeps the ends of the scale', () => {
    expect(suggestionText('real', '1.00')).toBe('likely real · 100%')
    expect(suggestionText('fake', '0.50')).toBe('likely fake · 50%')
  })
})
