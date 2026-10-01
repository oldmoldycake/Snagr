import { describe, expect, it } from 'vitest'
import { returnPath } from './useSession'

describe('returnPath', () => {
  it('returns the deep link AuthGuard saved, query and hash included', () => {
    expect(returnPath({ from: '/items/42?range=30d#history' })).toBe('/items/42?range=30d#history')
  })

  it('falls back to the dashboard with nothing saved', () => {
    expect(returnPath(null)).toBe('/')
    expect(returnPath(undefined)).toBe('/')
    expect(returnPath({})).toBe('/')
  })

  it('refuses anything that is not an in-app path', () => {
    expect(returnPath({ from: '//evil.example/x' })).toBe('/')
    expect(returnPath({ from: 'https://evil.example' })).toBe('/')
    expect(returnPath({ from: 42 })).toBe('/')
  })
})
