import { http, HttpResponse, type DefaultBodyType, type StrictRequest } from 'msw'
import type { TimeRange } from '@/lib/time'
import { rangeToMs, TIME_RANGES } from '@/lib/time'
import type {
  CategoryCreateRequest,
  CategoryUpdateRequest,
  InviteAcceptRequest,
  InviteCreateRequest,
  ItemCreateRequest,
  ItemUpdateRequest,
  ListingUpdateRequest,
  LoginRequest,
  MeUpdateRequest,
  PasswordChangeRequest,
  RunCreateRequest,
  SiteCreateRequest,
  SiteUpdateRequest,
  AdminUserUpdateRequest,
  WatchUpdateRequest,
} from '@/api/types'
import {
  activeListings,
  bestPriceAt,
  cents,
  checksFor,
  downsample,
  itemListings,
  newId,
  NOW,
  store,
  targetMet,
  type MockCategory,
  type MockItem,
  type MockRun,
} from './fixtures'
import {
  toAdminUser,
  toCategory,
  toInvite,
  toItemDetail,
  toItemSummary,
  toListing,
  toRun,
  toRunEvent,
  toSite,
  toUser,
} from './serializers'
import { addClient, cancelDemoRun, hasActiveRun, removeClient, startDemoRun } from './sse'

const DAY = 86_400_000
const SESSION_KEY = 'snagr:mock-session'

// --- helpers -------------------------------------------------------------------

function err(status: number, code: string, message: string, extra: Record<string, unknown> = {}) {
  return HttpResponse.json({ error: { code, message, ...extra } }, { status })
}

function sessionUser() {
  const raw = localStorage.getItem(SESSION_KEY)
  if (!raw) return null
  return store.users.find((u) => u.id === Number(raw) && u.is_active) ?? null
}

function requireUser() {
  const user = sessionUser()
  if (!user) throw err(401, 'unauthenticated', 'Not signed in')
  return user
}

function requireAdmin() {
  const user = requireUser()
  if (user.role !== 'admin') throw err(403, 'forbidden', 'Admin access required')
  return user
}

function rangeParam(request: StrictRequest<DefaultBodyType>): TimeRange {
  const url = new URL(request.url)
  const raw = url.searchParams.get('range')
  return TIME_RANGES.includes(raw as TimeRange) ? (raw as TimeRange) : '30d'
}

function intParam(request: StrictRequest<DefaultBodyType>, name: string, fallback: number): number {
  const raw = new URL(request.url).searchParams.get(name)
  const n = Number(raw)
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : fallback
}

const slugify = (name: string) =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')

/** Simulated network latency so loading states are visible. */
const wait = () => new Promise((r) => setTimeout(r, 120 + Math.random() * 180))

interface TrackingFields {
  criteria: string | null
  selection_mode: 'cheapest' | 'best_match'
  max_listings: number
  allow_reproductions: boolean
  site_ids: number[] | null
}

/**
 * Normalize + validate the tracking fields shared by item create/update.
 * `existing` supplies defaults on PATCH; omitted fields keep their value.
 * site_ids must be a subset of the category's sites; empty/full set → null.
 */
function validateTracking(
  body: ItemCreateRequest | ItemUpdateRequest,
  category: MockCategory,
  existing?: MockItem,
): TrackingFields | HttpResponse<DefaultBodyType> {
  const criteria =
    body.criteria !== undefined ? body.criteria?.trim() || null : (existing?.criteria ?? null)

  const selection_mode = body.selection_mode ?? existing?.selection_mode ?? 'cheapest'
  if (selection_mode !== 'cheapest' && selection_mode !== 'best_match') {
    return err(422, 'validation_error', 'Invalid selection mode', {
      fields: { selection_mode: "Must be 'cheapest' or 'best_match'" },
    })
  }

  const max_listings = body.max_listings ?? existing?.max_listings ?? 5
  if (!Number.isInteger(max_listings) || max_listings < 1 || max_listings > 10) {
    return err(422, 'validation_error', 'Max listings must be between 1 and 10', {
      fields: { max_listings: 'Must be between 1 and 10' },
    })
  }

  const allow_reproductions = body.allow_reproductions ?? existing?.allow_reproductions ?? false

  let site_ids = body.site_ids !== undefined ? body.site_ids : (existing?.site_ids ?? null)
  if (site_ids != null) {
    if (site_ids.some((id) => !category.site_ids.includes(id))) {
      return err(422, 'validation_error', "site_ids must be a subset of the category's sites", {
        fields: { site_ids: "Must be a subset of the category's linked sites" },
      })
    }
    // empty or the full category set means "all sites"
    if (site_ids.length === 0 || site_ids.length === category.site_ids.length) site_ids = null
  }

  return { criteria, selection_mode, max_listings, allow_reproductions, site_ids }
}

// --- handlers --------------------------------------------------------------------

export const handlers = [
  // ---- instance / auth ----
  http.get('/api/instance', async () => {
    await wait()
    return HttpResponse.json({
      version: '0.1.0-mock',
      ntfy_server_url: 'https://ntfy.example.com',
      registration_open: store.users.length === 0,
      oidc_provider_name: null,
    })
  }),

  http.post('/api/auth/login', async ({ request }) => {
    await wait()
    const body = (await request.json()) as LoginRequest
    const user = store.users.find((u) => u.email === body.email && u.password === body.password)
    if (!user || !user.is_active) {
      return err(401, 'invalid_credentials', 'Email or password is incorrect')
    }
    localStorage.setItem(SESSION_KEY, String(user.id))
    return HttpResponse.json({ user: toUser(user) })
  }),

  http.post('/api/auth/register', async ({ request }) => {
    await wait()
    if (store.users.length > 0) {
      return err(403, 'registration_closed', 'Registration is closed — ask your admin for an invite')
    }
    const body = (await request.json()) as LoginRequest
    const user = {
      id: newId(),
      email: body.email,
      password: body.password,
      role: 'admin' as const,
      is_active: true,
      ntfy_topic: null,
      created_at: Date.now(),
    }
    store.users.push(user)
    localStorage.setItem(SESSION_KEY, String(user.id))
    return HttpResponse.json({ user: toUser(user) }, { status: 201 })
  }),

  http.post('/api/auth/refresh', async () => {
    return sessionUser() ? new HttpResponse(null, { status: 204 }) : err(401, 'unauthenticated', 'Refresh token expired')
  }),

  http.post('/api/auth/logout', async () => {
    localStorage.removeItem(SESSION_KEY)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/auth/me', async () => {
    const user = sessionUser()
    if (!user) return err(401, 'unauthenticated', 'Not signed in')
    return HttpResponse.json(toUser(user))
  }),

  http.get('/api/auth/invites/:token', async ({ params }) => {
    await wait()
    const invite = store.invites.find((i) => i.token === params.token)
    if (!invite) return err(404, 'not_found', 'This invite link is not valid')
    if (invite.accepted_at || invite.expires_at < Date.now()) {
      return err(410, 'invite_expired', 'This invite has expired or was already used')
    }
    return HttpResponse.json({ email: invite.email, expires_at: new Date(invite.expires_at).toISOString() })
  }),

  http.post('/api/auth/invites/:token/accept', async ({ params, request }) => {
    await wait()
    const invite = store.invites.find((i) => i.token === params.token)
    if (!invite) return err(404, 'not_found', 'This invite link is not valid')
    if (invite.accepted_at || invite.expires_at < Date.now()) {
      return err(410, 'invite_expired', 'This invite has expired or was already used')
    }
    const body = (await request.json()) as InviteAcceptRequest
    const user = {
      id: newId(),
      email: invite.email ?? body.email,
      password: body.password,
      role: 'user' as const,
      is_active: true,
      ntfy_topic: null,
      created_at: Date.now(),
    }
    store.users.push(user)
    invite.accepted_at = Date.now()
    localStorage.setItem(SESSION_KEY, String(user.id))
    return HttpResponse.json({ user: toUser(user) }, { status: 201 })
  }),

  // ---- me ----
  http.patch('/api/me', async ({ request }) => {
    const user = requireUser()
    const body = (await request.json()) as MeUpdateRequest
    if (body.email !== undefined) user.email = body.email
    if (body.ntfy_topic !== undefined) user.ntfy_topic = body.ntfy_topic
    return HttpResponse.json(toUser(user))
  }),

  http.post('/api/me/password', async ({ request }) => {
    const user = requireUser()
    const body = (await request.json()) as PasswordChangeRequest
    if (user.password !== body.current_password) {
      return err(422, 'invalid_password', 'Current password is incorrect', {
        fields: { current_password: 'Current password is incorrect' },
      })
    }
    user.password = body.new_password
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/me/ntfy/test', async () => {
    const user = requireUser()
    await wait()
    if (!user.ntfy_topic) {
      return err(422, 'no_topic', 'Set a ntfy topic before sending a test notification')
    }
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- categories ----
  http.get('/api/categories', async () => {
    requireUser()
    await wait()
    return HttpResponse.json({ data: store.categories.map(toCategory) })
  }),

  http.post('/api/categories', async ({ request }) => {
    requireUser()
    const body = (await request.json()) as CategoryCreateRequest
    const name = body.name?.trim()
    if (!name) return err(422, 'validation_error', 'Name is required', { fields: { name: 'Name is required' } })
    if (store.categories.some((c) => c.name.toLowerCase() === name.toLowerCase())) {
      return err(422, 'duplicate', 'A category with this name already exists', {
        fields: { name: 'A category with this name already exists' },
      })
    }
    const category = { id: newId(), name, slug: slugify(name), site_ids: [] }
    store.categories.push(category)
    return HttpResponse.json(toCategory(category), { status: 201 })
  }),

  http.patch('/api/categories/:id', async ({ params, request }) => {
    requireUser()
    const category = store.categories.find((c) => c.id === Number(params.id))
    if (!category) return err(404, 'not_found', `Category ${params.id} does not exist`)
    const body = (await request.json()) as CategoryUpdateRequest
    if (body.name) {
      category.name = body.name.trim()
      category.slug = slugify(category.name)
    }
    return HttpResponse.json(toCategory(category))
  }),

  http.delete('/api/categories/:id', async ({ params }) => {
    requireUser()
    const id = Number(params.id)
    const itemIds = new Set(store.items.filter((i) => i.category_id === id).map((i) => i.id))
    store.categories = store.categories.filter((c) => c.id !== id)
    store.items = store.items.filter((i) => !itemIds.has(i.id))
    store.watches = store.watches.filter((w) => !itemIds.has(w.item_id))
    const listingIds = new Set(store.listings.filter((l) => itemIds.has(l.item_id)).map((l) => l.id))
    store.listings = store.listings.filter((l) => !listingIds.has(l.id))
    store.checks = store.checks.filter((c) => !listingIds.has(c.listing_id))
    return new HttpResponse(null, { status: 204 })
  }),

  http.put('/api/categories/:id/sites', async ({ params, request }) => {
    requireUser()
    const category = store.categories.find((c) => c.id === Number(params.id))
    if (!category) return err(404, 'not_found', `Category ${params.id} does not exist`)
    const body = (await request.json()) as { site_ids: number[] }
    category.site_ids = body.site_ids.filter((id) => store.sites.some((s) => s.id === id))
    return HttpResponse.json(toCategory(category))
  }),

  // ---- sites ----
  http.get('/api/sites', async () => {
    requireUser()
    await wait()
    return HttpResponse.json({ data: store.sites.map(toSite) })
  }),

  http.post('/api/sites', async ({ request }) => {
    requireUser()
    const body = (await request.json()) as SiteCreateRequest
    if (!body.name?.trim() || !body.base_url?.trim()) {
      return err(422, 'validation_error', 'Name and base URL are required')
    }
    const site = {
      id: newId(),
      name: body.name.trim(),
      base_url: body.base_url.trim().replace(/\/$/, ''),
      created_at: Date.now(),
    }
    store.sites.push(site)
    return HttpResponse.json(toSite(site), { status: 201 })
  }),

  http.patch('/api/sites/:id', async ({ params, request }) => {
    requireUser()
    const site = store.sites.find((s) => s.id === Number(params.id))
    if (!site) return err(404, 'not_found', `Site ${params.id} does not exist`)
    const body = (await request.json()) as SiteUpdateRequest
    if (body.name) site.name = body.name.trim()
    if (body.base_url) site.base_url = body.base_url.trim().replace(/\/$/, '')
    return HttpResponse.json(toSite(site))
  }),

  http.delete('/api/sites/:id', async ({ params }) => {
    requireUser()
    const id = Number(params.id)
    store.sites = store.sites.filter((s) => s.id !== id)
    for (const category of store.categories) {
      category.site_ids = category.site_ids.filter((sid) => sid !== id)
    }
    for (const listing of store.listings) {
      if (listing.site_id === id) listing.active = false
    }
    return new HttpResponse(null, { status: 204 })
  }),

  // ---- items ----
  http.get('/api/items', async ({ request }) => {
    requireUser()
    await wait()
    const url = new URL(request.url)
    const range = rangeParam(request)
    const categoryId = url.searchParams.get('category_id')
    const siteId = url.searchParams.get('site_id')
    const status = url.searchParams.get('status') ?? 'all'
    const search = url.searchParams.get('search')?.toLowerCase()
    const page = intParam(request, 'page', 1)
    const perPage = intParam(request, 'per_page', 50)

    let items = [...store.items]
    if (categoryId) items = items.filter((i) => i.category_id === Number(categoryId))
    if (siteId) {
      items = items.filter((i) =>
        store.listings.some((l) => l.item_id === i.id && l.active && l.site_id === Number(siteId)),
      )
    }
    if (search) items = items.filter((i) => i.name.toLowerCase().includes(search))

    let rows = items.map((i) => toItemSummary(i, range))
    if (status === 'snagged') rows = rows.filter((r) => r.target_met)
    if (status === 'above_target') rows = rows.filter((r) => !r.target_met && r.active_listing_count > 0)
    if (status === 'no_listings') rows = rows.filter((r) => r.active_listing_count === 0)

    const total = rows.length
    rows = rows.slice((page - 1) * perPage, page * perPage)
    return HttpResponse.json({ data: rows, meta: { page, per_page: perPage, total } })
  }),

  http.post('/api/items', async ({ request }) => {
    requireUser()
    const body = (await request.json()) as ItemCreateRequest
    if (!body.name?.trim()) {
      return err(422, 'validation_error', 'Name is required', { fields: { name: 'Name is required' } })
    }
    const category = store.categories.find((c) => c.id === body.category_id)
    if (!category) {
      return err(404, 'not_found', `Category ${body.category_id} does not exist`)
    }
    const tracking = validateTracking(body, category)
    if (tracking instanceof HttpResponse) return tracking
    const item = {
      id: newId(),
      category_id: body.category_id,
      name: body.name.trim(),
      target_cents: body.target_price != null ? Math.round(Number(body.target_price) * 100) : null,
      criteria: tracking.criteria,
      selection_mode: tracking.selection_mode,
      max_listings: tracking.max_listings,
      site_ids: tracking.site_ids,
      created_at: Date.now(),
    }
    store.items.push(item)
    store.watches.push({ id: newId(), item_id: item.id, notify: true, target_cents: null })
    return HttpResponse.json(toItemSummary(item), { status: 201 })
  }),

  http.get('/api/items/:id', async ({ params }) => {
    requireUser()
    await wait()
    const item = store.items.find((i) => i.id === Number(params.id))
    if (!item) return err(404, 'not_found', `Item ${params.id} does not exist`)
    return HttpResponse.json(toItemDetail(item))
  }),

  http.patch('/api/items/:id', async ({ params, request }) => {
    requireUser()
    const item = store.items.find((i) => i.id === Number(params.id))
    if (!item) return err(404, 'not_found', `Item ${params.id} does not exist`)
    const body = (await request.json()) as ItemUpdateRequest
    const category = store.categories.find((c) => c.id === item.category_id)!
    const tracking = validateTracking(body, category, item)
    if (tracking instanceof HttpResponse) return tracking
    if (body.name !== undefined) item.name = body.name.trim()
    if (body.target_price !== undefined) {
      item.target_cents = body.target_price != null ? Math.round(Number(body.target_price) * 100) : null
    }
    item.criteria = tracking.criteria
    item.selection_mode = tracking.selection_mode
    item.max_listings = tracking.max_listings
    item.site_ids = tracking.site_ids
    return HttpResponse.json(toItemDetail(item))
  }),

  http.delete('/api/items/:id', async ({ params }) => {
    requireUser()
    const id = Number(params.id)
    store.items = store.items.filter((i) => i.id !== id)
    store.watches = store.watches.filter((w) => w.item_id !== id)
    const listingIds = new Set(store.listings.filter((l) => l.item_id === id).map((l) => l.id))
    store.listings = store.listings.filter((l) => l.item_id !== id)
    store.checks = store.checks.filter((c) => !listingIds.has(c.listing_id))
    return new HttpResponse(null, { status: 204 })
  }),

  http.patch('/api/items/:id/watch', async ({ params, request }) => {
    requireUser()
    const watch = store.watches.find((w) => w.item_id === Number(params.id))
    if (!watch) return err(404, 'not_found', `Item ${params.id} does not exist`)
    const body = (await request.json()) as WatchUpdateRequest
    if (body.notify !== undefined) watch.notify = body.notify
    if (body.target_price !== undefined) {
      watch.target_cents = body.target_price != null ? Math.round(Number(body.target_price) * 100) : null
    }
    return HttpResponse.json({ id: watch.id, notify: watch.notify, target_price: cents(watch.target_cents) })
  }),

  http.patch('/api/listings/:id', async ({ params, request }) => {
    requireUser()
    const listing = store.listings.find((l) => l.id === Number(params.id))
    if (!listing) return err(404, 'not_found', `Listing ${params.id} does not exist`)
    const body = (await request.json()) as ListingUpdateRequest
    listing.active = body.active
    return HttpResponse.json(toListing(listing))
  }),

  http.get('/api/items/:id/price-checks', async ({ params, request }) => {
    requireUser()
    await wait()
    const limit = intParam(request, 'limit', 50)
    const listingIds = new Set(itemListings(Number(params.id)).map((l) => l.id))
    const checks = store.checks
      .filter((c) => listingIds.has(c.listing_id))
      .sort((a, b) => b.ts - a.ts)
      .slice(0, limit)
      .map((c) => {
        const listing = store.listings.find((l) => l.id === c.listing_id)!
        return {
          id: c.id,
          listing_id: c.listing_id,
          site_name: store.sites.find((s) => s.id === listing.site_id)!.name,
          price: cents(c.price_cents),
          currency: 'USD',
          in_stock: c.in_stock,
          status: c.status,
          checked_at: new Date(c.ts).toISOString(),
        }
      })
    return HttpResponse.json({ data: checks })
  }),

  // ---- charts / aggregates ----
  http.get('/api/items/:id/price-history', async ({ params, request }) => {
    requireUser()
    await wait()
    const item = store.items.find((i) => i.id === Number(params.id))
    if (!item) return err(404, 'not_found', `Item ${params.id} does not exist`)
    const range = rangeParam(request)
    const points = Math.min(500, intParam(request, 'points', 300))
    const rangeMs = rangeToMs(range)
    const start = rangeMs === Number.POSITIVE_INFINITY ? 0 : NOW - rangeMs

    const series = activeListings(item.id).map((listing) => {
      const all = checksFor(listing.id)
      const inRange = all.filter((c) => c.ts >= start)
      // synthetic first point: the last check before the cutoff, clamped to it
      const before = all.filter((c) => c.ts < start && c.price_cents != null).at(-1)
      const checks = before ? [{ ...before, ts: start }, ...inRange] : inRange
      return {
        listing_id: listing.id,
        site_name: store.sites.find((s) => s.id === listing.site_id)!.name,
        title: listing.title,
        active: listing.active,
        points: downsample(checks, points).map((c) => ({
          ts: new Date(c.ts).toISOString(),
          price: cents(c.price_cents)!,
          in_stock: c.in_stock,
        })),
      }
    })

    return HttpResponse.json({
      item_id: item.id,
      target_price: cents(item.target_cents),
      currency: 'USD',
      range,
      series,
    })
  }),

  http.get('/api/items/:id/price-summary', async ({ params, request }) => {
    requireUser()
    await wait()
    const item = store.items.find((i) => i.id === Number(params.id))
    if (!item) return err(404, 'not_found', `Item ${params.id} does not exist`)
    const range = rangeParam(request)
    const points = Math.min(500, intParam(request, 'points', 300))
    const rangeMs = rangeToMs(range)
    const start = rangeMs === Number.POSITIVE_INFINITY ? NOW - 365 * DAY : NOW - rangeMs
    const buckets = Math.min(points, 120)
    const width = (NOW - start) / buckets

    const listings = activeListings(item.id)
    const out: { ts: string; avg: string | null; best: string | null }[] = []
    for (let b = 0; b < buckets; b++) {
      const bucketEnd = start + (b + 1) * width
      // carry-forward latest price per listing as of the bucket end
      const prices: number[] = []
      for (const listing of listings) {
        let latest: number | null = null
        let latestTs = 0
        for (const c of store.checks) {
          if (c.listing_id === listing.id && c.price_cents != null && c.ts <= bucketEnd && c.ts > latestTs) {
            latest = c.price_cents
            latestTs = c.ts
          }
        }
        if (latest != null) prices.push(latest)
      }
      out.push({
        ts: new Date(start + b * width + width / 2).toISOString(),
        avg: prices.length ? (prices.reduce((a, c) => a + c, 0) / prices.length / 100).toFixed(2) : null,
        best: prices.length ? (Math.min(...prices) / 100).toFixed(2) : null,
      })
    }

    return HttpResponse.json({
      item_id: item.id,
      target_price: cents(item.target_cents),
      currency: 'USD',
      range,
      points: out,
    })
  }),

  http.get('/api/categories/:id/price-change', async ({ params, request }) => {
    requireUser()
    await wait()
    const category = store.categories.find((c) => c.id === Number(params.id))
    if (!category) return err(404, 'not_found', `Category ${params.id} does not exist`)
    const range = rangeParam(request)
    const rangeMs = rangeToMs(range)
    const start = rangeMs === Number.POSITIVE_INFINITY ? 0 : NOW - rangeMs

    const items = store.items
      .filter((i) => i.category_id === category.id)
      .map((item) => {
        const oldBest = bestPriceAt(item.id, start)
        const nowBest = bestPriceAt(item.id, NOW)
        let pct: string | null = null
        if (oldBest != null && nowBest != null && oldBest > 0) {
          const change = ((nowBest - oldBest) / oldBest) * 100
          pct = `${change >= 0 ? '+' : ''}${change.toFixed(2)}`
        }
        return {
          item_id: item.id,
          name: item.name,
          pct_change: pct,
          old_best: cents(oldBest),
          new_best: cents(nowBest),
        }
      })

    return HttpResponse.json({ category_id: category.id, range, items })
  }),

  http.get('/api/dashboard/stats', async ({ request }) => {
    requireUser()
    await wait()
    const range = rangeParam(request)
    const rangeMs = rangeToMs(range)
    const start = rangeMs === Number.POSITIVE_INFINITY ? NOW - 365 * DAY : NOW - rangeMs
    const prevStart = start - (NOW - start)

    const trackedNow = store.items.length
    const trackedPrev = store.items.filter((i) => i.created_at < start).length
    const listingsNow = store.listings.filter((l) => l.active).length
    const listingsPrev = store.listings.filter((l) => l.active && l.created_at < start).length

    const dropsIn = (from: number, to: number) => countDrops(from, to)
    const dropsNow = dropsIn(start, NOW)
    const dropsPrev = dropsIn(prevStart, start)

    const snaggedNow = store.items.filter((i) => targetMet(i.id)).length

    const growthSpark = (current: number, previous: number) => {
      const spark: number[] = []
      for (let b = 0; b < 12; b++) spark.push(Math.round(previous + ((current - previous) * b) / 11))
      return spark
    }

    return HttpResponse.json({
      tracked_items: { value: trackedNow, delta: trackedNow - trackedPrev, spark: growthSpark(trackedNow, trackedPrev) },
      active_listings: { value: listingsNow, delta: listingsNow - listingsPrev, spark: growthSpark(listingsNow, listingsPrev) },
      price_drops: { value: dropsNow, delta: dropsNow - dropsPrev, spark: growthSpark(dropsNow, Math.max(0, dropsPrev)) },
      snagged: { value: snaggedNow, delta: Math.min(snaggedNow, 1), spark: growthSpark(snaggedNow, Math.max(0, snaggedNow - 1)) },
    })
  }),

  http.get('/api/dashboard/price-drops', async ({ request }) => {
    requireUser()
    await wait()
    const range = rangeParam(request)
    const limit = intParam(request, 'limit', 10)
    const rangeMs = rangeToMs(range)
    const start = rangeMs === Number.POSITIVE_INFINITY ? 0 : NOW - rangeMs

    const drops: {
      item_id: number
      item_name: string
      listing_id: number
      site_name: string
      old_price: string
      new_price: string
      currency: string
      pct_change: string
      checked_at: string
    }[] = []

    for (const listing of store.listings) {
      if (!listing.active) continue
      const checks = checksFor(listing.id).filter((c) => c.price_cents != null)
      for (let i = checks.length - 1; i > 0; i--) {
        const curr = checks[i]
        if (curr.ts < start) break
        const prev = checks[i - 1]
        if (prev.price_cents! > curr.price_cents! && (prev.price_cents! - curr.price_cents!) / prev.price_cents! > 0.03) {
          const item = store.items.find((it) => it.id === listing.item_id)
          if (!item) break
          drops.push({
            item_id: item.id,
            item_name: item.name,
            listing_id: listing.id,
            site_name: store.sites.find((s) => s.id === listing.site_id)!.name,
            old_price: cents(prev.price_cents)!,
            new_price: cents(curr.price_cents)!,
            currency: 'USD',
            pct_change: (((curr.price_cents! - prev.price_cents!) / prev.price_cents!) * 100).toFixed(2),
            checked_at: new Date(curr.ts).toISOString(),
          })
          break // one drop per listing keeps the table varied
        }
      }
    }

    drops.sort((a, b) => new Date(b.checked_at).getTime() - new Date(a.checked_at).getTime())
    return HttpResponse.json({ data: drops.slice(0, limit) })
  }),

  // ---- runs ----
  http.post('/api/runs', async ({ request }) => {
    requireUser()
    const active = hasActiveRun()
    if (active) {
      return err(409, 'run_in_progress', 'A run is already active', { run_id: active.id })
    }
    const body = (await request.json()) as RunCreateRequest
    let label = 'Everything'
    if (body.scope === 'category') {
      const c = store.categories.find((x) => x.id === body.scope_id)
      if (!c) return err(404, 'not_found', `Category ${body.scope_id} does not exist`)
      label = `Category: ${c.name}`
    } else if (body.scope === 'site') {
      const s = store.sites.find((x) => x.id === body.scope_id)
      if (!s) return err(404, 'not_found', `Site ${body.scope_id} does not exist`)
      label = `Site: ${s.name}`
    } else if (body.scope === 'item') {
      const i = store.items.find((x) => x.id === body.scope_id)
      if (!i) return err(404, 'not_found', `Item ${body.scope_id} does not exist`)
      label = `Item: ${i.name}`
    }

    const run: MockRun = {
      id: newId(),
      scope: body.scope,
      scope_id: body.scope_id ?? null,
      scope_label: label,
      status: 'queued',
      started_at: null,
      finished_at: null,
      stats: null,
      error: null,
      created_at: Date.now(),
      last_seq: 0,
    }
    store.runs.push(run)
    startDemoRun(run)
    return HttpResponse.json({ run: toRun(run) }, { status: 202 })
  }),

  http.get('/api/runs', async ({ request }) => {
    requireUser()
    await wait()
    const url = new URL(request.url)
    const status = url.searchParams.get('status')
    const page = intParam(request, 'page', 1)
    const perPage = intParam(request, 'per_page', 25)
    let runs = [...store.runs].sort((a, b) => b.created_at - a.created_at)
    if (status) runs = runs.filter((r) => r.status === status)
    const total = runs.length
    runs = runs.slice((page - 1) * perPage, page * perPage)
    return HttpResponse.json({ data: runs.map(toRun), meta: { page, per_page: perPage, total } })
  }),

  http.get('/api/runs/:id', async ({ params }) => {
    requireUser()
    const run = store.runs.find((r) => r.id === Number(params.id))
    if (!run) return err(404, 'not_found', `Run ${params.id} does not exist`)
    return HttpResponse.json(toRun(run))
  }),

  http.get('/api/runs/:id/events', async ({ params, request }) => {
    requireUser()
    const afterSeq = intParam(request, 'after_seq', 0)
    const limit = intParam(request, 'limit', 500)
    const events = store.runEvents
      .filter((e) => e.run_id === Number(params.id) && e.seq > afterSeq)
      .sort((a, b) => a.seq - b.seq)
      .slice(0, limit)
    return HttpResponse.json({ data: events.map(toRunEvent) })
  }),

  http.post('/api/runs/:id/cancel', async ({ params }) => {
    requireUser()
    const run = store.runs.find((r) => r.id === Number(params.id))
    if (!run) return err(404, 'not_found', `Run ${params.id} does not exist`)
    if (run.status !== 'queued' && run.status !== 'running') {
      return err(409, 'not_active', 'This run has already finished')
    }
    cancelDemoRun(run)
    return HttpResponse.json(toRun(run))
  }),

  // ---- SSE ----
  http.get('/api/events', () => {
    const user = sessionUser()
    if (!user) return err(401, 'unauthenticated', 'Not signed in')

    let client: { enqueue: (chunk: string) => void }
    let heartbeat: ReturnType<typeof setInterval>
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        client = {
          enqueue: (chunk: string) => {
            try {
              controller.enqueue(encoder.encode(chunk))
            } catch {
              removeClient(client)
            }
          },
        }
        addClient(client)
        heartbeat = setInterval(() => client.enqueue(': ping\n\n'), 15_000)
      },
      cancel() {
        clearInterval(heartbeat)
        removeClient(client)
      },
    })

    return new HttpResponse(stream, {
      headers: {
        'Content-Type': 'text/event-stream',
        'Cache-Control': 'no-cache',
        'X-Accel-Buffering': 'no',
      },
    })
  }),

  // ---- admin ----
  http.get('/api/admin/users', async () => {
    requireAdmin()
    await wait()
    return HttpResponse.json({ data: store.users.map(toAdminUser) })
  }),

  http.patch('/api/admin/users/:id', async ({ params, request }) => {
    requireAdmin()
    const user = store.users.find((u) => u.id === Number(params.id))
    if (!user) return err(404, 'not_found', `User ${params.id} does not exist`)
    const body = (await request.json()) as AdminUserUpdateRequest
    if (body.is_active !== undefined) user.is_active = body.is_active
    if (body.role !== undefined) user.role = body.role
    return HttpResponse.json(toAdminUser(user))
  }),

  http.delete('/api/admin/users/:id', async ({ params }) => {
    const admin = requireAdmin()
    const id = Number(params.id)
    if (id === admin.id) return err(422, 'cannot_delete_self', 'You cannot delete your own account')
    store.users = store.users.filter((u) => u.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/admin/invites', async () => {
    requireAdmin()
    await wait()
    return HttpResponse.json({
      data: store.invites.filter((i) => !i.accepted_at && i.expires_at > Date.now()).map(toInvite),
    })
  }),

  http.post('/api/admin/invites', async ({ request }) => {
    requireAdmin()
    const body = (await request.json()) as InviteCreateRequest
    const invite = {
      id: newId(),
      token: crypto.randomUUID().replace(/-/g, ''),
      email: body.email?.trim() || null,
      expires_at: Date.now() + 7 * DAY,
      accepted_at: null,
      created_at: Date.now(),
    }
    store.invites.push(invite)
    return HttpResponse.json(toInvite(invite), { status: 201 })
  }),

  http.delete('/api/admin/invites/:id', async ({ params }) => {
    requireAdmin()
    store.invites = store.invites.filter((i) => i.id !== Number(params.id))
    return new HttpResponse(null, { status: 204 })
  }),
]

function countDrops(from: number, to: number): number {
  let count = 0
  for (const listing of store.listings) {
    if (!listing.active) continue
    const checks = checksFor(listing.id).filter((c) => c.price_cents != null && c.ts >= from && c.ts <= to)
    for (let i = 1; i < checks.length; i++) {
      if (
        checks[i - 1].price_cents! > checks[i].price_cents! &&
        (checks[i - 1].price_cents! - checks[i].price_cents!) / checks[i - 1].price_cents! > 0.03
      ) {
        count++
        break // count listings with a drop, not every wiggle
      }
    }
  }
  return count
}
