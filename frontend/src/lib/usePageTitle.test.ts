import { describe, expect, it } from 'vitest'
import { pageTitle } from './usePageTitle'

describe('pageTitle', () => {
  it('puts the page name ahead of the app name', () => {
    expect(pageTitle('RTX 4060 Ti 16GB')).toBe('RTX 4060 Ti 16GB · Snagr')
  })

  it('is the bare app name for a page with no name yet', () => {
    expect(pageTitle(undefined)).toBe('Snagr')
    expect(pageTitle('')).toBe('Snagr')
  })
})
