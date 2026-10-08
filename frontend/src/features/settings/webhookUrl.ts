const MASK = '••••'

/**
 * A webhook URL as the channel list shows it until asked: scheme and host, the
 * rest masked. A Discord webhook's token is in its path, and other hooks carry
 * theirs in the path or query, so whoever sees the whole URL can post to the
 * channel. The host still says where alerts go. Discord accepts suffixes after
 * the token (`/slack`, `?wait=true`), so masking only the last path segment
 * would leave it on screen. Anything that doesn't parse is masked whole.
 */
export function maskWebhookUrl(url: string): string {
  let parsed: URL
  try {
    parsed = new URL(url)
  } catch {
    return MASK
  }
  if (parsed.href === `${parsed.origin}/`) return parsed.origin
  return `${parsed.origin}/${MASK}`
}
