import type {
  AdminUser,
  AgentRun,
  Category,
  Invite,
  ItemDetail,
  ItemSummary,
  Listing,
  RunEvent,
  Site,
  User,
} from '@/api/types'
import type { TimeRange } from '@/lib/time'
import { rangeToMs } from '@/lib/time'
import {
  activeListings,
  avgPriceCents,
  bestPriceAt,
  bestPriceCents,
  cents,
  effectiveTargetCents,
  itemListings,
  latestCheck,
  NOW,
  sparkline,
  store,
  targetMet,
  type MockItem,
  type MockListing,
  type MockRun,
  type MockRunEvent,
  type MockUser,
} from './fixtures'

const iso = (ts: number | null): string | null => (ts == null ? null : new Date(ts).toISOString())

export function toUser(u: MockUser): User {
  return {
    id: u.id,
    email: u.email,
    role: u.role,
    ntfy_topic: u.ntfy_topic,
    created_at: iso(u.created_at)!,
  }
}

export function toAdminUser(u: MockUser): AdminUser {
  return {
    id: u.id,
    email: u.email,
    role: u.role,
    is_active: u.is_active,
    created_at: iso(u.created_at)!,
    item_count: store.items.length, // single-user mock: all items belong to the demo user
  }
}

export function toCategory(c: (typeof store.categories)[number]): Category {
  const items = store.items.filter((i) => i.category_id === c.id)
  return {
    id: c.id,
    name: c.name,
    slug: c.slug,
    site_ids: c.site_ids,
    item_count: items.length,
    snagged_count: items.filter((i) => targetMet(i.id)).length,
  }
}

export function toSite(s: (typeof store.sites)[number]): Site {
  const listings = store.listings.filter((l) => l.site_id === s.id)
  let lastChecked: number | null = null
  for (const l of listings) {
    const check = latestCheck(l.id)
    if (check && (lastChecked == null || check.ts > lastChecked)) lastChecked = check.ts
  }
  return {
    id: s.id,
    name: s.name,
    base_url: s.base_url,
    category_ids: store.categories.filter((c) => c.site_ids.includes(s.id)).map((c) => c.id),
    listing_count: listings.filter((l) => l.active).length,
    last_checked_at: iso(lastChecked),
    created_at: iso(s.created_at)!,
  }
}

export function toItemSummary(item: MockItem, range: TimeRange = '30d'): ItemSummary {
  const rangeMs = rangeToMs(range)
  const category = store.categories.find((c) => c.id === item.category_id)!
  const watch = store.watches.find((w) => w.item_id === item.id)!
  const best = bestPriceCents(item.id)
  const listings = activeListings(item.id)

  let lastChecked: number | null = null
  for (const l of listings) {
    const check = latestCheck(l.id)
    if (check && (lastChecked == null || check.ts > lastChecked)) lastChecked = check.ts
  }

  const rangeStart = rangeMs === Number.POSITIVE_INFINITY ? 0 : NOW - rangeMs
  const oldBest = bestPriceAt(item.id, rangeStart)
  let pct: string | null = null
  if (oldBest != null && best != null && oldBest > 0) {
    const change = ((best.cents - oldBest) / oldBest) * 100
    pct = `${change >= 0 ? '+' : ''}${change.toFixed(2)}`
  }

  return {
    id: item.id,
    name: item.name,
    category_id: category.id,
    category_name: category.name,
    category_slug: category.slug,
    target_price: cents(item.target_cents),
    currency: 'USD',
    criteria: item.criteria,
    selection_mode: item.selection_mode,
    max_listings: item.max_listings,
    site_ids: item.site_ids,
    best_price: best ? cents(best.cents) : null,
    best_listing_id: best?.listing.id ?? null,
    best_site_name: best ? store.sites.find((s) => s.id === best.listing.site_id)!.name : null,
    avg_price: cents(avgPriceCents(item.id)),
    active_listing_count: listings.length,
    target_met: targetMet(item.id),
    pct_change_range: pct,
    last_checked_at: iso(lastChecked),
    created_at: iso(item.created_at)!,
    watch: { id: watch.id, notify: watch.notify, target_price: cents(watch.target_cents) },
    spark: sparkline(item.id, rangeMs).map((c) => (c == null ? null : (c / 100).toFixed(2))),
  }
}

export function toListing(l: MockListing): Listing {
  const check = latestCheck(l.id)
  // latest check of ANY kind (including terminal sold/ended checks with no price)
  const lastAny = store.checks
    .filter((c) => c.listing_id === l.id)
    .reduce<(typeof store.checks)[number] | null>((max, c) => (max == null || c.ts > max.ts ? c : max), null)
  return {
    id: l.id,
    site_id: l.site_id,
    site_name: store.sites.find((s) => s.id === l.site_id)!.name,
    url: l.url,
    title: l.title,
    site_sku: l.site_sku,
    active: l.active,
    latest_price: check ? cents(check.price_cents) : null,
    in_stock: check?.in_stock ?? null,
    latest_status: lastAny?.status ?? null,
    match_score: l.match_score,
    match_summary: l.match_summary,
    last_checked_at: iso(lastAny?.ts ?? null),
    created_at: iso(l.created_at)!,
    discovered_by_run_id: l.discovered_by_run_id,
  }
}

export function toItemDetail(item: MockItem, range: TimeRange = '30d'): ItemDetail {
  return {
    ...toItemSummary(item, range),
    listings: itemListings(item.id).map(toListing),
  }
}

export function toRun(r: MockRun): AgentRun {
  return {
    id: r.id,
    scope: r.scope,
    scope_id: r.scope_id,
    scope_label: r.scope_label,
    status: r.status,
    started_at: iso(r.started_at),
    finished_at: iso(r.finished_at),
    stats: r.stats,
    error: r.error,
    created_at: iso(r.created_at)!,
    last_seq: r.last_seq,
  }
}

export function toRunEvent(e: MockRunEvent): RunEvent {
  return {
    run_id: e.run_id,
    seq: e.seq,
    ts: iso(e.ts)!,
    level: e.level,
    event_type: e.event_type as RunEvent['event_type'],
    message: e.message,
    payload: e.payload,
  }
}

export function toInvite(i: (typeof store.invites)[number]): Invite {
  return {
    id: i.id,
    token: i.token,
    email: i.email,
    expires_at: iso(i.expires_at)!,
    created_at: iso(i.created_at)!,
  }
}

export function effectiveTarget(itemId: number): string | null {
  return cents(effectiveTargetCents(itemId))
}
