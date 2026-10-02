import { describe, expect, it } from 'vitest'
import { renameNote } from './renameNote'

describe('renameNote', () => {
  it('says nothing when only the caller tracks the item', () => {
    expect(renameNote(1, true)).toBeNull()
    expect(renameNote(1, false)).toBeNull()
  })

  it('warns an admin that the rename is for everyone', () => {
    expect(renameNote(2, true)).toBe(
      '1 other person tracks this item too, so renaming it changes the name for them as well.',
    )
  })

  it('tells anyone else the rename is theirs alone', () => {
    expect(renameNote(4, false)).toBe(
      '3 other people track this item too, so renaming it changes the name for you only.',
    )
  })
})
