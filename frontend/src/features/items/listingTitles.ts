/**
 * The longest whole-word prefix every known title shares — usually the item's
 * own name, which marketplace titles repeat. Cutting it lets near-identical
 * listings read by their differences. Empty with fewer than two titles.
 */
export function sharedTitlePrefix(titles: (string | null)[]): string {
  const known = titles.filter((t): t is string => t != null)
  if (known.length < 2) return ''
  let prefix = known[0]
  for (const t of known) while (!t.startsWith(prefix)) prefix = prefix.slice(0, -1)
  if (known.some((t) => t.length > prefix.length && t[prefix.length] !== ' ')) {
    prefix = prefix.slice(0, prefix.lastIndexOf(' ') + 1)
  }
  return prefix
}

/**
 * What sets one title apart once the shared prefix is cut, without the
 * separator or brackets the cut leaves behind: "RTX 4060 Ti 16GB (Renewed)" →
 * "Renewed", "… — Used, Good" → "Used, Good". Empty when the title is nothing
 * but the prefix, or unknown.
 */
export function titleDifference(title: string | null, sharedPrefix: string): string {
  if (title == null) return ''
  const rest = (title.startsWith(sharedPrefix) ? title.slice(sharedPrefix.length) : title)
    .replace(/^[\s,:;|/·•–—-]+/, '')
    .trim()
  return rest.match(/^\(([^()]*)\)$/)?.[1] ?? rest
}

/**
 * A chart series' name, read the way its listing row reads: site first, then
 * what sets the listing apart — "amazon.com · Renewed". The difference is cut
 * short rather than the label, so the site always survives.
 */
export function seriesLabel(siteName: string, title: string | null, sharedPrefix: string): string {
  const difference = titleDifference(title, sharedPrefix)
  if (!difference) return siteName
  return `${siteName} · ${difference.length > 26 ? `${difference.slice(0, 25).trimEnd()}…` : difference}`
}
