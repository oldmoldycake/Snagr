/**
 * Mock SSE: a broadcast hub feeding every open /api/events stream, plus the
 * scripted "demo run" that plays out an agent run in real time, writing real
 * price checks into the fixture store as it goes.
 */

import {
  activeListings,
  latestCheck,
  newId,
  store,
  type MockItem,
  type MockListing,
  type MockRun,
} from './fixtures'
import { toRun, toRunEvent } from './serializers'

type StreamClient = { enqueue: (chunk: string) => void }

const clients = new Set<StreamClient>()

export function addClient(client: StreamClient) {
  clients.add(client)
  // snapshot on every (re)connect — the client backfills gaps from it
  const active = store.runs.filter((r) => r.status === 'queued' || r.status === 'running')
  client.enqueue(
    encode('run.snapshot', {
      active_runs: active.map((r) => ({
        id: r.id,
        status: r.status,
        scope: r.scope,
        scope_label: r.scope_label,
        last_seq: r.last_seq,
      })),
    }),
  )
}

export function removeClient(client: StreamClient) {
  clients.delete(client)
}

function encode(event: string, data: unknown, id?: string): string {
  return `event: ${event}\n${id ? `id: ${id}\n` : ''}data: ${JSON.stringify(data)}\n\n`
}

function broadcast(event: string, data: unknown, id?: string) {
  const chunk = encode(event, data, id)
  for (const client of clients) client.enqueue(chunk)
}

// --- demo run script ----------------------------------------------------------

const timers = new Map<number, ReturnType<typeof setTimeout>[]>()

export function hasActiveRun(): MockRun | undefined {
  return store.runs.find((r) => r.status === 'queued' || r.status === 'running')
}

export function cancelDemoRun(run: MockRun) {
  for (const t of timers.get(run.id) ?? []) clearTimeout(t)
  timers.delete(run.id)
  run.status = 'cancelled'
  run.finished_at = Date.now()
  emit(run, 'warn', 'run_finished', 'Run cancelled')
  broadcast('run.finished', { run: toRun(run) })
}

function emit(
  run: MockRun,
  level: 'info' | 'success' | 'warn' | 'error',
  event_type: string,
  message: string,
  payload: Record<string, unknown> | null = null,
) {
  run.last_seq += 1
  const event = {
    run_id: run.id,
    seq: run.last_seq,
    ts: Date.now(),
    level,
    event_type,
    message,
    payload,
  }
  store.runEvents.push(event)
  broadcast('run.event', toRunEvent(event), `${run.id}:${event.seq}`)
}

function scopeListings(run: MockRun): MockListing[] {
  const all = store.listings.filter((l) => l.active)
  switch (run.scope) {
    case 'global':
      return all
    case 'category': {
      const itemIds = new Set(store.items.filter((i) => i.category_id === run.scope_id).map((i) => i.id))
      return all.filter((l) => itemIds.has(l.item_id))
    }
    case 'site':
      return all.filter((l) => l.site_id === run.scope_id)
    case 'item':
      return all.filter((l) => l.item_id === run.scope_id)
  }
}

/** best_match items in scope — the run plays out a criteria-evaluation sequence for one. */
function bestMatchItems(run: MockRun): MockItem[] {
  return store.items.filter((item) => {
    if (item.selection_mode !== 'best_match') return false
    switch (run.scope) {
      case 'global':
        return true
      case 'category':
        return item.category_id === run.scope_id
      case 'item':
        return item.id === run.scope_id
      case 'site': {
        const category = store.categories.find((c) => c.id === item.category_id)
        const effective = item.site_ids ?? category?.site_ids ?? []
        return effective.includes(run.scope_id!)
      }
    }
  })
}

/** Items in scope that have no listings — the run "discovers" one. */
function discoverableItems(run: MockRun) {
  const inScope = (itemId: number) => {
    const item = store.items.find((i) => i.id === itemId)!
    if (run.scope === 'global') return true
    if (run.scope === 'category') return item.category_id === run.scope_id
    if (run.scope === 'item') return item.id === run.scope_id
    return false
  }
  return store.items.filter((i) => activeListings(i.id).length === 0 && inScope(i.id))
}

export function startDemoRun(run: MockRun) {
  const runTimers: ReturnType<typeof setTimeout>[] = []
  timers.set(run.id, runTimers)
  const at = (ms: number, fn: () => void) => runTimers.push(setTimeout(fn, ms))

  // Sample down to ~10 listings so the demo stays ~15s
  const listings = scopeListings(run)
  const step = Math.max(1, Math.floor(listings.length / 10))
  const sampled = listings.filter((_, i) => i % step === 0).slice(0, 10)
  const discoveries = discoverableItems(run).slice(0, 1)

  const stats = { listings_checked: 0, prices_found: 0, new_listings: 0, errors: 0 }
  let clock = 400

  at(clock, () => {
    run.status = 'running'
    run.started_at = Date.now()
    broadcast('run.started', { run: toRun(run) })
    emit(run, 'info', 'run_started', `Run started — ${run.scope_label}`)
  })

  const seenSites = new Set<number>()
  for (const listing of sampled) {
    const site = store.sites.find((s) => s.id === listing.site_id)!
    const item = store.items.find((i) => i.id === listing.item_id)!

    if (!seenSites.has(site.id)) {
      seenSites.add(site.id)
      clock += 350
      at(clock, () => emit(run, 'info', 'site_started', `Opening ${site.name}…`))
    }

    clock += 500 + Math.floor(Math.random() * 500)
    at(clock, () => emit(run, 'info', 'listing_check', `Checking ${site.name} for ${item.name}…`, { listing_id: listing.id, item_id: item.id }))

    clock += 400 + Math.floor(Math.random() * 400)
    at(clock, () => {
      stats.listings_checked++
      const prev = latestCheck(listing.id)
      // occasionally fail one check to exercise the error rendering
      if (stats.errors === 0 && Math.random() < 0.12) {
        stats.errors++
        emit(run, 'error', 'error', `${site.name} — price element not found for ${item.name}`, { listing_id: listing.id })
        return
      }
      const base = prev?.price_cents ?? 30000
      // mostly small moves; ~15% of checks are a real drop
      const move = Math.random() < 0.15 ? -(0.05 + Math.random() * 0.1) : (Math.random() - 0.5) * 0.02
      const price = Math.max(500, Math.round(base * (1 + move)))
      store.checks.push({
        id: newId(),
        listing_id: listing.id,
        ts: Date.now(),
        price_cents: price,
        in_stock: true,
        status: 'ok',
      })
      stats.prices_found++
      const dollars = (price / 100).toFixed(2)
      emit(run, 'success', 'price_found', `${site.name} — ${item.name}: $${dollars} ✓`, {
        listing_id: listing.id,
        item_id: item.id,
        price: dollars,
      })
    })
  }

  for (const item of discoveries) {
    const category = store.categories.find((c) => c.id === item.category_id)!
    const site = store.sites.find((s) => s.id === category.site_ids[0])!
    clock += 700
    at(clock, () => emit(run, 'info', 'item_started', `Searching ${site.name} for "${item.name}"…`, { item_id: item.id }))
    clock += 900
    at(clock, () => {
      const listing: MockListing = {
        id: newId(),
        item_id: item.id,
        site_id: site.id,
        url: `${site.base_url}/p/${item.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
        title: item.name,
        site_sku: null,
        active: true,
        match_score: null,
        match_summary: null,
        created_at: Date.now(),
        discovered_by_run_id: run.id,
      }
      store.listings.push(listing)
      const price = Math.round((item.target_cents ?? 20000) * (1.05 + Math.random() * 0.2))
      store.checks.push({
        id: newId(),
        listing_id: listing.id,
        ts: Date.now(),
        price_cents: price,
        in_stock: true,
        status: 'ok',
      })
      stats.new_listings++
      stats.prices_found++
      emit(run, 'success', 'listing_discovered', `Found new listing on ${site.name} for ${item.name} — $${(price / 100).toFixed(2)}`, {
        listing_id: listing.id,
        item_id: item.id,
      })
    })
  }

  // --- criteria evaluation for one best_match item in scope ------------------
  const bmItem = bestMatchItems(run)[0]
  if (bmItem) {
    const category = store.categories.find((c) => c.id === bmItem.category_id)!
    const siteId = (bmItem.site_ids ?? category.site_ids)[0]
    const site = store.sites.find((s) => s.id === siteId)!
    const itmUrl = () => `${site.base_url}/itm/${Math.floor(100000000 + Math.random() * 899999999)}`

    clock += 700
    at(clock, () =>
      emit(run, 'info', 'item_started', `Evaluating ${site.name} candidates for ${bmItem.name} against your criteria…`, {
        item_id: bmItem.id,
      }),
    )

    // a candidate that doesn't clear the ~50 match floor
    clock += 900
    at(clock, () => {
      const title = `${bmItem.name} — Mint, Sealed`
      emit(run, 'info', 'listing_evaluated', `${site.name} — "${title}" — match 34, below threshold, skipped`, {
        item_id: bmItem.id,
        url: itmUrl(),
        title,
        match_score: 34,
        match_summary: 'condition too good — does not fit your criteria',
        tracked: false,
      })
    })

    // a tracked listing sells → slot freed
    clock += 800
    at(clock, () => {
      const tracked = store.listings.filter((l) => l.item_id === bmItem.id && l.active)
      const lowest = [...tracked].sort((a, b) => (a.match_score ?? 0) - (b.match_score ?? 0))[0]
      if (!lowest) return
      lowest.active = false
      store.checks.push({
        id: newId(),
        listing_id: lowest.id,
        ts: Date.now(),
        price_cents: null,
        in_stock: false,
        status: 'sold',
      })
      emit(run, 'warn', 'listing_ended', `${site.name} — "${lowest.title ?? bmItem.name}" sold — slot freed`, {
        listing_id: lowest.id,
        item_id: bmItem.id,
      })
    })

    // refill the freed slot with the next best candidate
    clock += 1000
    at(clock, () => {
      const trackedCount = store.listings.filter((l) => l.item_id === bmItem.id && l.active).length
      if (trackedCount >= bmItem.max_listings) return
      const title = `${bmItem.name} — Used, Heavy Wear, Tested & Working`
      const score = 79 + Math.floor(Math.random() * 10)
      const listing: MockListing = {
        id: newId(),
        item_id: bmItem.id,
        site_id: site.id,
        url: itmUrl(),
        title,
        site_sku: null,
        active: true,
        match_score: score,
        match_summary: 'fits your criteria — condition and authenticity check out',
        created_at: Date.now(),
        discovered_by_run_id: run.id,
      }
      store.listings.push(listing)
      const basis = bmItem.target_cents ?? 15000
      const price = Math.round(basis * (0.95 + Math.random() * 0.25))
      store.checks.push({
        id: newId(),
        listing_id: listing.id,
        ts: Date.now(),
        price_cents: price,
        in_stock: true,
        status: 'ok',
      })
      stats.new_listings++
      stats.prices_found++
      emit(run, 'info', 'listing_evaluated', `${site.name} — "${title}" — match ${score} ✓`, {
        item_id: bmItem.id,
        url: listing.url,
        title,
        match_score: score,
        match_summary: listing.match_summary,
        tracked: true,
      })
      emit(run, 'success', 'listing_discovered', `Filled the freed slot with the next best match — $${(price / 100).toFixed(2)}`, {
        listing_id: listing.id,
        item_id: bmItem.id,
      })
    })
  }

  clock += 600
  at(clock, () => {
    run.status = 'succeeded'
    run.finished_at = Date.now()
    run.stats = stats
    emit(
      run,
      'success',
      'run_finished',
      `Run complete — ${stats.listings_checked} checked, ${stats.prices_found} prices, ${stats.new_listings} new listing${stats.new_listings === 1 ? '' : 's'}, ${stats.errors} error${stats.errors === 1 ? '' : 's'}`,
    )
    broadcast('run.finished', { run: toRun(run) })
    timers.delete(run.id)
  })
}
