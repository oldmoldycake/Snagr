/**
 * What happens next for an item just added, shown under the "Added" toast.
 * Hunting can be off for the item or for the whole server, and then nothing
 * is searched for it on its own, so the note says so rather than promise it.
 */
export function addedNote(itemHunts: boolean, serverHunts: boolean): string {
  if (!serverHunts) return "Hunting is off on this server, so Snagr won't search for listings until it's back on."
  if (!itemHunts) return 'Snagr searches for listings only when you press Hunt now.'
  return 'Snagr will start looking for listings shortly.'
}
