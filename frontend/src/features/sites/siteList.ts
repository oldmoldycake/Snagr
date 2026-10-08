/** Site names as prose: "eBay", "eBay and Amazon", "eBay, Newegg and Amazon", "eBay, Newegg and 2 more". */
export function siteList(names: string[]): string {
  if (names.length <= 1) return names.join('')
  if (names.length <= 3) return `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
  return `${names.slice(0, 2).join(', ')} and ${names.length - 2} more`
}
