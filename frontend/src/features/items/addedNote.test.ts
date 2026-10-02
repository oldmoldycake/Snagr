import { describe, expect, it } from 'vitest'
import { addedNote } from './addedNote'

describe('addedNote', () => {
  it('promises a search when the item hunts on its own', () => {
    expect(addedNote(true, true)).toBe('Snagr will start looking for listings shortly.')
  })

  it('points at Hunt now when hunting is off for the item', () => {
    expect(addedNote(false, true)).toBe('Snagr searches for listings only when you press Hunt now.')
  })

  it('says nothing will be searched while hunting is off on the server', () => {
    const note = "Hunting is off on this server, so Snagr won't search for listings until it's back on."
    expect(addedNote(true, false)).toBe(note)
    expect(addedNote(false, false)).toBe(note)
  })
})
