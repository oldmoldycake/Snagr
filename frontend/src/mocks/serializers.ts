import type {
  AdminUser,
  ApiToken,
  Category,
  HuntFacts,
  Invite,
  Job,
  JobEvent,
  NotificationChannel,
  ItemDetail,
  ItemSummary,
  Listing,
  RecheckFacts,
  ReferenceImage,
  ReviewQueueEntry,
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
  type MockApiToken,
  type MockItem,
  type MockJob,
  type MockJobEvent,
  type MockListing,
  type MockNotificationChannel,
  type MockQueueEntry,
  type MockReference,
  type MockUser,
} from './fixtures'

const iso = (ts: number | null): string | null => (ts == null ? null : new Date(ts).toISOString())

export function toUser(u: MockUser): User {
  return {
    id: u.id,
    email: u.email,
    role: u.role,
    vision_auto_reject_fake: u.vision_auto_reject_fake,
    vision_auto_promote_real: u.vision_auto_promote_real,
    vision_auto_promote_fake: u.vision_auto_promote_fake,
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
    paused_until: iso(s.paused_until),
    paused_reason: s.paused_reason,
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
    allow_reproductions: item.allow_reproductions ?? false,
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
    authenticity: l.authenticity
      ? {
          verdict: l.authenticity.verdict,
          fake_confidence: l.authenticity.fake_confidence,
          image_count: l.authenticity.image_count,
          checked_at: iso(l.authenticity.checked_at)!,
        }
      : null,
    last_checked_at: iso(lastAny?.ts ?? null),
    created_at: iso(l.created_at)!,
    discovered_by_job_id: l.discovered_by_job_id,
  }
}

export function toReference(r: MockReference, viewer: MockUser): ReferenceImage {
  return {
    id: r.id,
    item_id: r.item_id,
    label: r.label,
    variant_tag: r.variant_tag,
    provenance: r.provenance,
    image_url: `/api/vision/images/${r.object_key}`,
    // a reference's source listing is visible only to its capturer and admins (D-V11)
    source_listing_url:
      viewer.role === 'admin' || r.captured_by === viewer.id ? r.source_listing_url : null,
    revoked: r.revoked,
    created_at: iso(r.created_at)!,
  }
}

export function toQueueEntry(e: MockQueueEntry): ReviewQueueEntry {
  return {
    id: e.id,
    item_id: e.item_id,
    item_name: store.items.find((i) => i.id === e.item_id)!.name,
    image_url: `/api/vision/images/${e.object_key}`,
    listing_url: e.listing_url,
    suggested_label: e.suggested_label,
    confidence: e.confidence,
    llm_authenticity_read: e.llm_authenticity_read,
    created_at: iso(e.created_at)!,
  }
}

export function toItemDetail(item: MockItem, range: TimeRange = '30d'): ItemDetail {
  return {
    ...toItemSummary(item, range),
    listings: itemListings(item.id).map(toListing),
    hunt: huntFacts(item),
    recheck: recheckFacts(item),
  }
}

/** PR 2a has no per-watch interval: every listing is re-read on the instance default. */
export const RECHECK_INTERVAL_MINUTES = 30

/** What the hunter will do next for this item — read off its jobs, never stored. */
function huntFacts(item: MockItem): HuntFacts {
  const hunts = store.jobs.filter((j) => j.kind === 'hunt' && j.item_id === item.id)
  const pending = hunts.filter((j) => j.status === 'pending').map((j) => j.run_after)
  const last = hunts
    .filter((j) => j.finished_at != null)
    .reduce<MockJob | null>((newest, j) => (newest == null || j.finished_at! > newest.finished_at! ? j : newest), null)
  return {
    running: hunts.some((j) => j.status === 'running'),
    next_at: pending.length ? iso(Math.min(...pending)) : null,
    last_at: iso(last?.finished_at ?? null),
    last_result: last == null ? null : lastResult(last),
    slots_open: Math.max(0, item.max_listings - activeListings(item.id).length),
  }
}

function lastResult(job: MockJob): HuntFacts['last_result'] {
  if (job.status === 'failed') return 'failed'
  if (job.status === 'cancelled') return 'cancelled'
  return (job.stats?.new_listings ?? 0) > 0 ? 'found' : 'nothing'
}

function recheckFacts(item: MockItem): RecheckFacts {
  const checks = store.jobs.filter((j) => j.kind === 'recheck' && j.item_id === item.id)
  const pending = checks.filter((j) => j.status === 'pending').map((j) => j.run_after)
  return {
    running: checks.filter((j) => j.status === 'running').length,
    next_at: pending.length ? iso(Math.min(...pending)) : null,
    interval_minutes: RECHECK_INTERVAL_MINUTES,
  }
}

/** Kind is said in words, not glyphs — the label is what every list row shows. */
export function jobLabel(job: MockJob): string {
  const itemName = store.items.find((i) => i.id === job.item_id)?.name ?? 'Unknown item'
  const siteName = store.sites.find((s) => s.id === job.site_id)?.name
  if (job.kind === 'hunt') return `${itemName} × ${siteName ?? 'every site'}`
  if (job.kind === 'ground') return `${itemName} · market price`
  return `${itemName} · check`
}

export function toJob(j: MockJob): Job {
  return {
    id: j.id,
    kind: j.kind,
    status: j.status,
    user_id: j.user_id,
    watch_id: j.watch_id,
    item_id: j.item_id,
    item_name: store.items.find((i) => i.id === j.item_id)?.name ?? null,
    site_id: j.site_id,
    site_name: store.sites.find((s) => s.id === j.site_id)?.name ?? null,
    listing_id: j.listing_id,
    label: jobLabel(j),
    priority: j.priority,
    run_after: iso(j.run_after)!,
    attempts: j.attempts,
    started_at: iso(j.started_at),
    finished_at: iso(j.finished_at),
    error: j.error,
    stats: j.stats,
    reason: j.reason,
    last_seq: j.last_seq,
    created_at: iso(j.created_at)!,
  }
}

export function toJobEvent(e: MockJobEvent): JobEvent {
  return {
    job_id: e.job_id,
    seq: e.seq,
    ts: iso(e.ts)!,
    level: e.level,
    event_type: e.event_type as JobEvent['event_type'],
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

export function toNotificationChannel(c: MockNotificationChannel): NotificationChannel {
  return {
    id: c.id,
    kind: c.kind,
    name: c.name,
    url: c.url,
    topic: c.topic,
    has_secret: c.secret != null,
    events: c.events,
    enabled: c.enabled,
    created_at: iso(c.created_at)!,
  }
}

export function toApiToken(t: MockApiToken): ApiToken {
  return {
    id: t.id,
    name: t.name,
    scopes: t.scopes,
    expires_at: iso(t.expires_at),
    last_used_at: iso(t.last_used_at),
    created_at: iso(t.created_at)!,
  }
}

export function effectiveTarget(itemId: number): string | null {
  return cents(effectiveTargetCents(itemId))
}
