import type { Site } from '@/api/types'

const SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i

/** What a typed site address is stored as: `https://` when no scheme was given, no trailing slash. */
export function normalizeBaseUrl(input: string): string {
  const trimmed = input.trim()
  const withScheme = SCHEME.test(trimmed) ? trimmed : `https://${trimmed}`
  return withScheme.replace(/\/+$/, '')
}

/** The address's hostname without a leading `www.`, or null when it doesn't parse as a URL. */
export function hostOf(url: string): string | null {
  try {
    return new URL(normalizeBaseUrl(url)).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

/**
 * Whether the typed address could be a site: a dotted host and no spaces.
 * Client-side only, because the backend accepts any string as a base URL.
 */
export function isPlausibleUrl(input: string): boolean {
  if (/\s/.test(input.trim())) return false
  const host = hostOf(input)
  return host != null && /^[^.]+(\.[^.]+)+$/.test(host)
}

/** The listed site on the same host as the typed address, so adding it again picks that one instead. */
export function findDuplicate(input: string, sites: Site[]): Site | undefined {
  const host = hostOf(input)
  if (host == null) return undefined
  return sites.find((site) => hostOf(site.base_url) === host)
}

/** A new site's name until the user types one: its host, matching how existing sites are named. */
export function defaultSiteName(input: string): string {
  return hostOf(input) ?? ''
}
