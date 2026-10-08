/**
 * The site_ids to store once `id` is ticked or unticked among `searched`, the
 * sites an item searches now: null (no restriction) when that comes to all
 * `siteCount` of its category's sites. Unticking the only site left is refused
 * with the message to show instead: no sites is stored as no restriction too,
 * so it would quietly pick every site again.
 */
export function siteIdsAfterToggle(
  searched: number[],
  id: number,
  siteCount: number,
): { siteIds: number[] | null } | { error: string } {
  const next = searched.includes(id) ? searched.filter((s) => s !== id) : [...searched, id]
  if (next.length === 0) return { error: 'Keep at least one site. Snagr needs somewhere to look.' }
  return { siteIds: next.length === siteCount ? null : next }
}
