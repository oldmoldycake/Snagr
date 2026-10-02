/**
 * What a rename does for the others who track an item, or null when the caller
 * tracks it alone. The name is on the item they all share: an admin renames it
 * for everyone, while anyone else's tracking moves to an item of the new name.
 */
export function renameNote(watcherCount: number, isAdmin: boolean): string | null {
  const others = watcherCount - 1
  if (others < 1) return null
  const who = others === 1 ? '1 other person tracks' : `${others} other people track`
  return isAdmin
    ? `${who} this item too, so renaming it changes the name for them as well.`
    : `${who} this item too, so renaming it changes the name for you only.`
}
