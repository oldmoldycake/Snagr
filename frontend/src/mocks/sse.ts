/**
 * Mock SSE: a per-viewer hub feeding every open /api/events stream, plus the
 * two scripts that make the hunter look alive — a demo hunt that plays out in
 * real time when someone presses Hunt now, and a check loop that re-reads one
 * listing every ~20 s for as long as a stream is open. Both write real rows
 * into the fixture store, so what the page announces is what the next fetch
 * returns. Every frame is gated by the job-visibility predicate (jobVisible in
 * fixtures.ts), mirroring the backend hub.
 */

import {
  activeListings,
  jobVisible,
  latestCheck,
  newId,
  store,
  type MockJob,
  type MockJobEvent,
  type MockListing,
  type MockUser,
} from './fixtures'
import { toJob, toJobEvent } from './serializers'

export type StreamClient = { user: MockUser; enqueue: (chunk: string) => void }

const clients = new Set<StreamClient>()

export function addClient(client: StreamClient) {
  clients.add(client)
  // per-viewer snapshot on every (re)connect — the client rebuilds its live
  // set from it and refetches each backfill (the filtered response is
  // authoritative; no gap inference). Rechecks are not in it: they have no
  // events and are over in seconds.
  const live = store.jobs.filter(
    (j) =>
      j.kind !== 'recheck' &&
      (j.status === 'pending' || j.status === 'running') &&
      jobVisible(j, client.user),
  )
  client.enqueue(encode('job.snapshot', { jobs: live.map(toJob) }))
  startCheckLoop()
}

export function removeClient(client: StreamClient) {
  clients.delete(client)
  if (clients.size === 0) stopCheckLoop()
}

function encode(event: string, data: unknown, id?: string): string {
  return `event: ${event}\n${id ? `id: ${id}\n` : ''}data: ${JSON.stringify(data)}\n\n`
}

/** Lifecycle envelopes (job.started / job.finished / job.failed). */
function broadcastJob(event: string, job: MockJob) {
  const chunk = encode(event, { job: toJob(job) })
  for (const client of clients) {
    if (jobVisible(job, client.user)) client.enqueue(chunk)
  }
}

function broadcastJobEvent(job: MockJob, event: MockJobEvent) {
  const chunk = encode('job.event', toJobEvent(event), `${job.id}:${event.seq}`)
  for (const client of clients) {
    if (jobVisible(job, client.user)) client.enqueue(chunk)
  }
}

/** listing.checked goes to the listing's owner (and to admins). */
function broadcastCheck(listing: MockListing, data: unknown) {
  const chunk = encode('listing.checked', data)
  for (const client of clients) {
    const owns = store.watches.some(
      (w) => w.item_id === listing.item_id && w.user_id === client.user.id,
    )
    if (owns || client.user.role === 'admin') client.enqueue(chunk)
  }
}

function emit(
  job: MockJob,
  level: MockJobEvent['level'],
  event_type: string,
  message: string,
  payload: Record<string, unknown> | null = null,
) {
  job.last_seq += 1
  const event = {
    job_id: job.id,
    seq: job.last_seq,
    ts: Date.now(),
    level,
    event_type,
    message,
    payload,
  }
  store.jobEvents.push(event)
  broadcastJobEvent(job, event)
}

// --- the demo hunt ---------------------------------------------------------

const timers = new Map<number, ReturnType<typeof setTimeout>[]>()

export function cancelDemoHunt(job: MockJob) {
  for (const t of timers.get(job.id) ?? []) clearTimeout(t)
  timers.delete(job.id)
  const wasRunning = job.status === 'running'
  job.status = 'cancelled'
  job.finished_at = Date.now()
  if (wasRunning) emit(job, 'warn', 'job_finished', 'Cancelled by you')
  broadcastJob('job.finished', job)
}

/**
 * One hunt, played out over ~12 s: it looks at a few candidates, rejects some
 * against the item's criteria, and saves one — writing a real listing and a
 * real price check, so the item page shows the find the moment it lands.
 */
export function startDemoHunt(job: MockJob) {
  const jobTimers: ReturnType<typeof setTimeout>[] = []
  timers.set(job.id, jobTimers)
  const at = (ms: number, fn: () => void) => jobTimers.push(setTimeout(fn, ms))

  const item = store.items.find((i) => i.id === job.item_id)!
  const site = store.sites.find((s) => s.id === job.site_id)!
  const slotsOpen = Math.max(0, item.max_listings - activeListings(item.id).length)
  // a person's hunt on a full watch: its one save is a trade for the weakest
  const swap = slotsOpen === 0 && job.payload?.swap === true
  const stats = {
    listings_checked: 0,
    prices_found: 0,
    new_listings: 0,
    errors: 0,
    tokens_in: 0,
    tokens_out: 0,
    duration_ms: null as number | null,
    method: null,
    transport: null,
  }
  let clock = 400

  at(clock, () => {
    job.status = 'running'
    job.started_at = Date.now()
    broadcastJob('job.started', job)
    emit(
      job,
      'info',
      'job_started',
      (swap
        ? `Hunting ${site.name} for something better than "${item.name}"'s weakest tracked listing — ` +
          `all ${item.max_listings} slots filled`
        : `Hunting ${site.name} for "${item.name}" — ${slotsOpen} open slot${slotsOpen === 1 ? '' : 's'}`) +
        `, ${item.selection_mode === 'best_match' ? 'best match' : 'cheapest'} mode`,
    )
  })

  clock += 900
  at(clock, () =>
    emit(job, 'info', 'listing_check', `Searched "${item.name.toLowerCase()}" · 6 results, 2 already tracked`),
  )

  const REJECTED = [
    { title: `${item.name} — parts only, not working`, score: 14, why: 'parts, not a working unit' },
    { title: `${item.name} bundle with accessories`, score: 41, why: 'bundle — extras excluded by criteria' },
  ]
  for (const candidate of REJECTED) {
    clock += 1400
    at(clock, () => {
      stats.listings_checked += 1
      emit(
        job,
        'info',
        'listing_evaluated',
        `Skipped "${candidate.title}" — ${candidate.why} (match ${candidate.score})`,
        {
          item_id: item.id,
          url: `${site.base_url}/itm/${Math.floor(100000000 + Math.random() * 899999999)}`,
          title: candidate.title,
          match_score: candidate.score,
          match_summary: candidate.why,
          tracked: false,
        },
      )
    })
  }

  clock += 1600
  at(clock, () => {
    stats.listings_checked += 1
    if (slotsOpen === 0 && !swap) return
    // cheapest mode's weakest: the highest last price
    const weakest = swap
      ? activeListings(item.id)
          .map((l) => ({ listing: l, cents: latestCheck(l.id)?.price_cents ?? Infinity }))
          .sort((a, b) => b.cents - a.cents)[0]
      : null
    const title = `${item.name} — Used, Tested & Working`
    const score = 78 + Math.floor(Math.random() * 12)
    const listing: MockListing = {
      id: newId(),
      item_id: item.id,
      site_id: site.id,
      url: `${site.base_url}/itm/${Math.floor(100000000 + Math.random() * 899999999)}`,
      title,
      site_sku: null,
      active: true,
      match_score: score,
      match_summary: 'fits your criteria — condition and authenticity check out',
      created_at: Date.now(),
      discovered_by_job_id: job.id,
    }
    store.listings.push(listing)
    const price =
      weakest && Number.isFinite(weakest.cents)
        ? Math.round(weakest.cents * 0.9)
        : Math.round((item.target_cents ?? 20000) * (0.95 + Math.random() * 0.2))
    if (weakest) {
      weakest.listing.active = false
      emit(
        job,
        'info',
        'listing_ended',
        `Replaced listing #${weakest.listing.id} "${weakest.listing.title}" with listing #${listing.id} "${title}"`,
        { listing_id: weakest.listing.id, item_id: item.id, reason: 'replaced', replaced_by: listing.id },
      )
    }
    store.checks.push({
      id: newId(),
      listing_id: listing.id,
      ts: Date.now(),
      price_cents: price,
      in_stock: true,
      status: 'ok',
      method: 'jsonld',
      confirmed: true,
    })
    stats.prices_found += 1
    stats.new_listings += 1
    emit(
      job,
      'success',
      'price_found',
      `Price read $${(price / 100).toFixed(2)} · in stock · "${title}" (match ${score})`,
      { listing_id: listing.id, item_id: item.id, price: (price / 100).toFixed(2) },
    )
    emit(
      job,
      'success',
      'listing_discovered',
      `Saved as listing #${listing.id} — ${activeListings(item.id).length} of ${item.max_listings} slots filled · locator learned (jsonld)`,
      { listing_id: listing.id, item_id: item.id },
    )
  })

  clock += 1200
  at(clock, () => {
    job.status = 'done'
    job.finished_at = Date.now()
    stats.duration_ms = job.finished_at - (job.started_at ?? job.finished_at)
    stats.tokens_in = 8_200 + Math.floor(Math.random() * 4_000)
    stats.tokens_out = 600 + Math.floor(Math.random() * 500)
    job.stats = stats
    const left = Math.max(0, item.max_listings - activeListings(item.id).length)
    emit(
      job,
      'success',
      'job_finished',
      stats.new_listings > 0
        ? `Hunt complete — ${stats.new_listings} new · ${stats.listings_checked} seen · ${left} slots left`
        : `Hunt complete — nothing new · ${stats.listings_checked} seen`,
    )
    broadcastJob('job.finished', job)
    timers.delete(job.id)
  })
}

// --- the check loop --------------------------------------------------------

/** Cycled so the checks tail shows every way a price can be read. */
const CHECK_METHODS = ['jsonld', 'meta', 'locator', 'llm']
let checkLoop: ReturnType<typeof setInterval> | null = null
let checkCount = 0

function startCheckLoop() {
  if (checkLoop != null) return
  checkLoop = setInterval(runOneCheck, 20_000)
}

function stopCheckLoop() {
  if (checkLoop == null) return
  clearInterval(checkLoop)
  checkLoop = null
}

/**
 * One recheck, the way the daemon does it: a real price_checks row and the
 * frame the trigger would raise. Rechecks write no job events and emit no
 * lifecycle frames — this one frame is the whole of their output.
 */
function runOneCheck() {
  const tracked = store.listings.filter((l) => l.active)
  if (tracked.length === 0) return
  const listing = tracked[checkCount % tracked.length]
  const item = store.items.find((i) => i.id === listing.item_id)!
  const site = store.sites.find((s) => s.id === listing.site_id)!
  const method = CHECK_METHODS[checkCount % CHECK_METHODS.length]
  // one in twelve is a reading the bands did not believe — it shows in the
  // tail as unconfirmed and in nothing else
  const confirmed = checkCount % 12 !== 11
  checkCount += 1

  const base = latestCheck(listing.id)?.price_cents ?? 20000
  const price = confirmed
    ? Math.max(500, Math.round(base * (0.98 + Math.random() * 0.04)))
    : Math.round(base / 10)
  const check = {
    id: newId(),
    listing_id: listing.id,
    ts: Date.now(),
    price_cents: price,
    in_stock: true,
    status: 'ok',
    method,
    confirmed,
  }
  store.checks.push(check)

  broadcastCheck(listing, {
    listing_id: listing.id,
    item_id: item.id,
    item_name: item.name,
    site_name: site.name,
    price: (price / 100).toFixed(2),
    currency: 'USD',
    status: 'ok',
    method,
    confirmed,
    slot_freed: false,
    checked_at: new Date(check.ts).toISOString(),
  })
}
