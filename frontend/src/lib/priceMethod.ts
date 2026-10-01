/**
 * How a recheck read its price, in words a new user can follow. The API's
 * method codes ('jsonld', 'locator', …) name mechanisms; the screen only needs
 * to say that no AI was involved and roughly how. `llm` is the fallback, not
 * the news, so it has no tag; an unknown code shows as-is rather than vanish.
 */
export function priceMethodLabel(method: string | null | undefined): string | null {
  switch (method) {
    case null:
    case undefined:
    case 'llm':
      return null
    case 'jsonld':
    case 'meta':
    case 'microdata':
      return 'page data'
    case 'locator':
      return 'learned spot'
    default:
      return method
  }
}
