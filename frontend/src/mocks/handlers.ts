import { http, HttpResponse, type DefaultBodyType, type StrictRequest } from 'msw'
import type { TimeRange } from '@/lib/time'
import { rangeToMs, TIME_RANGES } from '@/lib/time'
import type {
  ApiTokenCreateRequest,
  ApiTokenScope,
  CategoryCreateRequest,
  CategoryUpdateRequest,
  InviteAcceptRequest,
  InviteCreateRequest,
  ItemCreateRequest,
  ItemUpdateRequest,
  JobCreateRequest,
  JobScope,
  ListingUpdateRequest,
  LoginRequest,
  MeUpdateRequest,
  NotificationChannelCreateRequest,
  NotificationChannelTestRequest,
  NotificationChannelUpdateRequest,
  NotificationEvent,
  PasswordChangeRequest,
  PasswordResetRequest,
  ReviewConfirmRequest,
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
  jobVisible,
  newId,
  NOW,
  store,
  targetMet,
  VISION_DEFAULTS,
  type MockCategory,
  type MockItem,
  type MockJob,
  type MockNotificationChannel,
  type MockUser,
} from './fixtures'
import {
  effectiveInterval,
  MAX_RECHECK_INTERVAL_MINUTES,
  HUNT_ENABLED,
  RECHECK_INTERVAL_FLOOR_MINUTES,
  RECHECK_INTERVAL_MINUTES,
  toAdminUser,
  toCategory,
  toInvite,
  toItemDetail,
  toItemSummary,
  toListing,
  toApiToken,
  toJob,
  toJobEvent,
  toNotificationChannel,
  toQueueEntry,
  toReference,
  toSite,
  toUser,
} from './serializers'
import { addClient, cancelDemoHunt, removeClient, startDemoHunt, type StreamClient } from './sse'

const DAY = 86_400_000
const MINUTE = 60_000
const TOKEN_SCOPES: ApiTokenScope[] = ['read', 'write', 'jobs']
const SESSION_KEY = 'snagr:mock-session'

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

/**
 * A new category's slug, never "" (a name of only emoji or symbols has no
 * letters to keep) and never one another category holds: "C++" after "C"
 * gets "c-2".
 */
function uniqueSlug(name: string) {
  const base =
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'category'
  let slug = base
  for (let n = 2; store.categories.some((c) => c.slug === slug); n++) slug = `${base}-${n}`
  return slug
}

/**
 * The backend's name rules for categories and sites, shared by create and
 * rename: trimmed, required, and unique ignoring case. The trimmed name, or
 * the 422 to answer with.
 */
function checkedName(
  rows: { id: number; name: string }[],
  noun: 'category' | 'site',
  name: string,
  exceptId?: number,
): string | HttpResponse<DefaultBodyType> {
  const trimmed = name.trim()
  if (!trimmed) return err(422, 'validation_error', 'Name is required', { fields: { name: 'Name is required' } })
  if (rows.some((r) => r.id !== exceptId && r.name.toLowerCase() === trimmed.toLowerCase())) {
    const message = `A ${noun} with this name already exists`
    return err(422, 'duplicate', message, { fields: { name: message } })
  }
  return trimmed
}

const MIN_PASSWORD_LENGTH = 8

/** The backend's rule for a new password; the 422 to answer with, or null when it passes. */
function weakPassword(password: string, field: 'password' | 'new_password') {
  if (password.length >= MIN_PASSWORD_LENGTH) return null
  const message = `Password must be at least ${MIN_PASSWORD_LENGTH} characters`
  return err(422, 'validation_error', message, { fields: { [field]: message } })
}

/**
 * The backend's email-taken 422, or null when no other account holds the
 * address. Addresses are stored lowercased and matched regardless of case.
 */
function emailTaken(email: string, exceptId?: number) {
  const key = email.toLowerCase()
  if (!store.users.some((u) => u.id !== exceptId && u.email.toLowerCase() === key)) return null
  const message = 'An account with this email already exists'
  return err(422, 'validation_error', message, { fields: { email: message } })
}

const SIGN_IN_LIMIT = 10
const SIGN_IN_WINDOW = 15 * MINUTE
const signInAttempts = new Map<string, number[]>()

/**
 * The backend's per-account sign-in limit: an attempt counts when it starts,
 * and an account with SIGN_IN_LIMIT of them in the window is refused, right
 * password or not. Counts this attempt, or returns the 429 without counting.
 * (The backend also limits each client address, which the mock has no notion of.)
 */
function signInAttempt(email: string) {
  const now = Date.now()
  const key = email.toLowerCase()
  const recent = (signInAttempts.get(key) ?? []).filter((at) => at > now - SIGN_IN_WINDOW)
  if (recent.length >= SIGN_IN_LIMIT) {
    const minutes = Math.ceil((recent[0] + SIGN_IN_WINDOW - now) / MINUTE)
    return err(429, 'rate_limited', `Too many sign-in attempts — try again in ${minutes} minute${minutes === 1 ? '' : 's'}`)
  }
  signInAttempts.set(key, [...recent, now])
  return null
}

/** Simulated network latency so loading states are visible. */
const wait = () => new Promise((r) => setTimeout(r, 120 + Math.random() * 180))

const JOB_KINDS: JobCreateRequest['kind'][] = ['hunt', 'recheck']
const JOB_SCOPES: JobScope[] = ['global', 'category', 'site', 'item']

function newJob(kind: MockJob['kind'], over: Partial<MockJob> = {}): MockJob {
  return {
    id: newId(),
    kind,
    status: 'pending',
    user_id: null,
    watch_id: null,
    item_id: null,
    site_id: null,
    listing_id: null,
    priority: 0,
    run_after: Date.now(),
    attempts: 0,
    started_at: null,
    finished_at: null,
    error: null,
    stats: null,
    reason: null,
    last_seq: 0,
    created_at: Date.now(),
    ...over,
  }
}

/**
 * The head start a person's hunt of a watch's index-th site gets: 100 for the
 * first, 10 less for each after it, so a batch of new items has every item's
 * first site hunted before anyone's second.
 */
function sitePriority(index: number): number {
  return Math.max(100 - index * 10, 0)
}

/**
 * At most one open hunt per (watch, site) — the partial unique index, in mock
 * form. A pending one is bumped to now with its backoff forgotten, a running
 * one is handed back untouched, and a watch with no open slot gets nothing at
 * all.
 */
function enqueueHunt(
  watchId: number,
  itemId: number,
  siteId: number,
  over: Partial<MockJob> = {},
): MockJob | null {
  const item = store.items.find((i) => i.id === itemId)!
  // a full watch is hunted only when a person asks, and that hunt is a swap
  // hunt that may trade the weakest tracked listing for something better
  if (activeListings(itemId).length >= item.max_listings && !over.payload?.swap) return null
  const open = store.jobs.find(
    (j) =>
      j.kind === 'hunt' &&
      j.watch_id === watchId &&
      j.site_id === siteId &&
      (j.status === 'pending' || j.status === 'running'),
  )
  if (open) {
    if (open.status === 'pending') {
      open.run_after = Date.now()
      open.priority = over.priority ?? open.priority
      open.reason = (over.reason as MockJob['reason']) ?? open.reason
      open.user_id = over.user_id ?? open.user_id
      open.payload = over.payload ?? null
    }
    return open
  }
  const job = newJob('hunt', { watch_id: watchId, item_id: itemId, site_id: siteId, ...over })
  store.jobs.push(job)
  return job
}

/**
 * A freed slot — or more room, or hunting switched back on — starts the
 * watch's hunts over: a waiting one the hunter queued itself is brought
 * forward with its backoff forgotten, a site with none gets one. Nothing for
 * a full watch, one switched off, or with hunting off for the instance.
 */
function wakeHunts(watchId: number, itemId: number, reason: MockJob['reason'] = 'slot_freed') {
  const item = store.items.find((i) => i.id === itemId)!
  if (!HUNT_ENABLED || item.hunt === false) return
  if (activeListings(itemId).length >= item.max_listings) return
  for (const job of store.jobs) {
    if (job.kind !== 'hunt' || job.watch_id !== watchId || job.status !== 'pending') continue
    if (job.user_id != null) continue
    job.run_after = Date.now()
    job.payload = null
    job.reason = reason
  }
  for (const siteId of sitesOf(itemId)) enqueueHunt(watchId, itemId, siteId, { reason })
}

/** The caller's watches inside a scope, or null when the scope target is unknown. */
function scopedWatches(user: MockUser, scope: JobScope, scopeId: number | null) {
  const mine = store.watches.filter((w) => w.user_id === user.id)
  if (scope === 'global') return mine
  if (scopeId == null) return null
  if (scope === 'category') {
    if (!store.categories.some((c) => c.id === scopeId)) return null
    const items = new Set(store.items.filter((i) => i.category_id === scopeId).map((i) => i.id))
    return mine.filter((w) => items.has(w.item_id))
  }
  if (scope === 'item') {
    if (!store.items.some((i) => i.id === scopeId)) return null
    return mine.filter((w) => w.item_id === scopeId)
  }
  if (!store.sites.some((s) => s.id === scopeId)) return null
  return mine.filter((w) => sitesOf(w.item_id).includes(scopeId))
}

/** Which sites a watch searches: its own subset, else its category's. */
function sitesOf(itemId: number): number[] {
  const item = store.items.find((i) => i.id === itemId)!
  const category = store.categories.find((c) => c.id === item.category_id)!
  return item.site_ids ?? category.site_ids
}

interface TrackingFields {
  criteria: string | null
  selection_mode: 'cheapest' | 'best_match'
  max_listings: number
  allow_reproductions: boolean
  recheck_interval_minutes: number | null
  hunt: boolean
  site_ids: number[] | null
}

/**
 * Normalize + validate the tracking fields shared by item create/update.
 * `existing` supplies defaults on PATCH; omitted fields keep their value.
 * An explicit null changes criteria (cleared), recheck_interval_minutes (back
 * to the instance default) and site_ids (every site of the category).
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

  const recheck_interval_minutes =
    body.recheck_interval_minutes !== undefined
      ? body.recheck_interval_minutes
      : (existing?.recheck_interval_minutes ?? null)
  if (
    recheck_interval_minutes != null &&
    (!Number.isInteger(recheck_interval_minutes) ||
      recheck_interval_minutes < RECHECK_INTERVAL_FLOOR_MINUTES ||
      recheck_interval_minutes > MAX_RECHECK_INTERVAL_MINUTES)
  ) {
    const range = `between ${RECHECK_INTERVAL_FLOOR_MINUTES} and ${MAX_RECHECK_INTERVAL_MINUTES} minutes`
    return err(422, 'validation_error', `Check interval must be ${range}`, {
      fields: { recheck_interval_minutes: `Must be ${range}` },
    })
  }

  const hunt = body.hunt ?? existing?.hunt ?? true

  let site_ids = body.site_ids !== undefined ? body.site_ids : (existing?.site_ids ?? null)
  if (site_ids != null) {
    if (site_ids.some((id) => !category.site_ids.includes(id))) {
      return err(422, 'validation_error', "site_ids must be a subset of the category's sites", {
        fields: { site_ids: "Must be a subset of the category's linked sites" },
      })
    }
    if (site_ids.length === 0 || site_ids.length === category.site_ids.length) site_ids = null
  }

  return {
    criteria,
    selection_mode,
    max_listings,
    allow_reproductions,
    recheck_interval_minutes,
    hunt,
    site_ids,
  }
}

/** The largest target watches.target_price (numeric(10, 2)) can hold, in cents. */
const MAX_TARGET_CENTS = 9_999_999_999

/**
 * A target price → cents (null = no target), or the 422 for anything but a
 * finite amount in whole cents from 0.01 to 99999999.99 — "NaN", "1,000",
 * "1e9", "0" and "1.001" alike.
 */
function parseTarget(value: string | null | undefined): number | null | HttpResponse<DefaultBodyType> {
  if (value == null) return null
  const amount = value.trim() === '' ? NaN : Number(value)
  const cents = Math.round(amount * 100)
  if (
    !Number.isFinite(amount) ||
    Math.abs(amount * 100 - cents) > 1e-6 ||
    cents < 1 ||
    cents > MAX_TARGET_CENTS
  ) {
    const bounds = 'between 0.01 and 99999999.99'
    return err(422, 'validation_error', `Target price must be an amount ${bounds}`, {
      fields: { target_price: `Must be an amount ${bounds}, in whole cents` },
    })
  }
  return cents
}

/** The category's item by this name, trimmed and ignoring case — how the backend matches them. */
function trackedName(categoryId: number, name: string) {
  const key = name.trim().toLowerCase()
  return store.items.find((i) => i.category_id === categoryId && i.name.toLowerCase() === key)
}

function alreadyTracked() {
  const message = 'You already track an item with this name'
  return err(422, 'duplicate', message, { fields: { name: message } })
}

const KNOWN_EVENTS: NotificationEvent[] = ['target.hit', 'listing.new']
const NTFY_TOPIC = /^[A-Za-z0-9_-]{1,64}$/
// every channel is another send per event, so one user can't queue unbounded work
const MAX_CHANNELS = 10

/**
 * Why a channel URL isn't a public address, or null — an approximation of
 * the backend's notifications.public_url (which checks every reserved range
 * via Python's ipaddress): container names, local names, credentials, and
 * the common private IPv4/IPv6 literals.
 */
function privateUrlProblem(raw: string): string | null {
  let url: URL
  try {
    url = new URL(raw)
  } catch {
    return 'not a valid URL'
  }
  if (url.username || url.password) return 'a URL carrying credentials is not accepted'
  const host = url.hostname.toLowerCase().replace(/\.$/, '')
  if (host.startsWith('[')) {
    return /^\[(::1?|::ffff:.*|f[c-d].*|fe[89ab].*)\]$/.test(host) ? `${host} is a private or reserved address` : null
  }
  // URL() normalizes the shorthand IPv4 spellings ("127.1") to dotted quads
  const quad = /^(\d+)\.(\d+)\.\d+\.\d+$/.exec(host)
  if (quad) {
    const [a, b] = [Number(quad[1]), Number(quad[2])]
    const reserved =
      [0, 10, 127].includes(a) ||
      a >= 224 ||
      (a === 100 && b >= 64 && b < 128) ||
      (a === 169 && b === 254) ||
      (a === 172 && b >= 16 && b < 32) ||
      (a === 192 && b === 168)
    return reserved ? `${host} is a private or reserved address` : null
  }
  if (!host.includes('.') || host === 'localhost' || /\.(localhost|internal|local|home\.arpa)$/.test(host)) {
    return `${host} is not a public hostname`
  }
  return null
}

interface ChannelFields {
  name: string
  url: string | null
  topic: string | null
  events: NotificationEvent[] | null
}

/**
 * Validate where a channel of this kind sends, clearing the field its kind
 * doesn't use. Saves and the unsaved test share it, so a test never reaches a
 * destination a save would refuse.
 */
function validateDestination(
  kind: MockNotificationChannel['kind'],
  url: string | null,
  topic: string | null,
): Pick<ChannelFields, 'url' | 'topic'> | HttpResponse<DefaultBodyType> {
  if (kind === 'ntfy') {
    if (!topic) {
      return err(422, 'validation_error', 'Topic is required', { fields: { topic: 'Topic is required' } })
    }
    if (!NTFY_TOPIC.test(topic)) {
      return err(422, 'validation_error', 'Not a valid ntfy topic', {
        fields: { topic: 'Use 1-64 letters, digits, - or _' },
      })
    }
    return { url: null, topic }
  }
  if (!url || !/^https?:\/\//.test(url)) {
    return err(422, 'validation_error', 'A valid URL is required', { fields: { url: 'Must be an http(s) URL' } })
  }
  if (kind === 'discord' && !/^https:\/\/(discord|discordapp)\.com\/api\/webhooks\//.test(url)) {
    return err(422, 'validation_error', 'Not a Discord webhook URL', {
      fields: { url: 'Must be a Discord incoming-webhook URL' },
    })
  }
  const problem = privateUrlProblem(url)
  if (problem) {
    return err(422, 'validation_error', 'Notifications can only be sent to a public address', {
      fields: { url: problem },
    })
  }
  return { url, topic: null }
}

/**
 * Normalize + validate the channel fields shared by create/update. `existing`
 * supplies defaults on PATCH; kind is immutable, so it always comes from the
 * existing row there. events must be a subset of the known events; empty/full
 * set → null ("every event"), the site_ids convention.
 */
function validateChannel(
  kind: MockNotificationChannel['kind'],
  body: NotificationChannelCreateRequest | NotificationChannelUpdateRequest,
  existing?: MockNotificationChannel,
): ChannelFields | HttpResponse<DefaultBodyType> {
  const name = body.name !== undefined ? body.name.trim() : (existing?.name ?? '')
  if (!name) {
    return err(422, 'validation_error', 'Name is required', { fields: { name: 'Name is required' } })
  }

  const destination = validateDestination(
    kind,
    body.url !== undefined ? body.url.trim() || null : (existing?.url ?? null),
    body.topic !== undefined ? body.topic.trim() || null : (existing?.topic ?? null),
  )
  if (destination instanceof HttpResponse) return destination

  let events = body.events !== undefined ? body.events : (existing?.events ?? null)
  if (events != null) {
    if (events.some((e) => !KNOWN_EVENTS.includes(e))) {
      return err(422, 'validation_error', 'events must be a subset of the known events', {
        fields: { events: 'Unknown event' },
      })
    }
    if (events.length === 0 || events.length === KNOWN_EVENTS.length) events = null
  }

  return { name, ...destination, events }
}

/** Every mock route — the behavioral oracle for the backend's status codes and `error.code`s. */
export const handlers = [
  http.get('/api/instance', async () => {
    await wait()
    return HttpResponse.json({
      version: '0.1.0-mock',
      ntfy_server_url: 'https://ntfy.example.com',
      registration_open: store.users.length === 0,
      oidc_provider_name: null,
      vision_enabled: true,
      mcp_enabled: true,
      recheck_interval_default: RECHECK_INTERVAL_MINUTES,
      recheck_interval_floor: RECHECK_INTERVAL_FLOOR_MINUTES,
      hunt_enabled: HUNT_ENABLED,
    })
  }),

  http.post('/api/auth/login', async ({ request }) => {
    await wait()
    const body = (await request.json()) as LoginRequest
    const limited = signInAttempt(body.email)
    if (limited) return limited
    const email = body.email.toLowerCase()
    const user = store.users.find((u) => u.email.toLowerCase() === email && u.password === body.password)
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
    const weak = weakPassword(body.password, 'password')
    if (weak) return weak
    const user = {
      id: newId(),
      email: body.email.toLowerCase(),
      password: body.password,
      role: 'admin' as const,
      is_active: true,
      ...VISION_DEFAULTS,
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
    const weak = weakPassword(body.password, 'password')
    if (weak) return weak
    // an invite pinned to an email wins over whatever the form submitted
    const email = (invite.email ?? body.email).toLowerCase()
    const taken = emailTaken(email)
    if (taken) return taken
    const user = {
      id: newId(),
      email,
      password: body.password,
      role: 'user' as const,
      is_active: true,
      ...VISION_DEFAULTS,
      created_at: Date.now(),
    }
    store.users.push(user)
    invite.accepted_at = Date.now()
    localStorage.setItem(SESSION_KEY, String(user.id))
    return HttpResponse.json({ user: toUser(user) }, { status: 201 })
  }),

  http.get('/api/auth/password-resets/:token', async ({ params }) => {
    await wait()
    const reset = store.passwordResets.find((r) => r.token === params.token)
    const user = store.users.find((u) => u.id === reset?.user_id)
    if (!reset || !user) return err(404, 'not_found', 'This reset link is not valid')
    if (reset.used_at || reset.expires_at < Date.now()) {
      return err(410, 'reset_expired', 'This reset link has expired or was already used')
    }
    return HttpResponse.json({ email: user.email, expires_at: new Date(reset.expires_at).toISOString() })
  }),

  http.post('/api/auth/password-resets/:token', async ({ params, request }) => {
    await wait()
    const reset = store.passwordResets.find((r) => r.token === params.token)
    const user = store.users.find((u) => u.id === reset?.user_id)
    if (!reset || !user) return err(404, 'not_found', 'This reset link is not valid')
    if (reset.used_at || reset.expires_at < Date.now()) {
      return err(410, 'reset_expired', 'This reset link has expired or was already used')
    }
    const body = (await request.json()) as PasswordResetRequest
    const weak = weakPassword(body.password, 'password')
    if (weak) return weak
    user.password = body.password
    reset.used_at = Date.now()
    // the backend signs the account out everywhere; the mock's one session is this browser's
    if (localStorage.getItem(SESSION_KEY) === String(user.id)) localStorage.removeItem(SESSION_KEY)
    return new HttpResponse(null, { status: 204 })
  }),

  http.patch('/api/me', async ({ request }) => {
    const user = requireUser()
    const body = (await request.json()) as MeUpdateRequest
    const thresholds = [
      'vision_auto_reject_fake',
      'vision_auto_promote_real',
      'vision_auto_promote_fake',
    ] as const
    const fields: Record<string, string> = {}
    for (const field of thresholds) {
      const raw = body[field]
      if (raw === undefined) continue
      const n = Number(raw)
      if (!Number.isFinite(n) || n < 0.5 || n > 1) fields[field] = 'Must be between 0.50 and 1.00'
    }
    if (Object.keys(fields).length > 0) {
      return err(422, 'validation_error', 'Thresholds must be between 0.50 and 1.00', { fields })
    }
    if (body.email !== undefined && body.email.toLowerCase() !== user.email.toLowerCase()) {
      const taken = emailTaken(body.email, user.id)
      if (taken) return taken
      user.email = body.email.toLowerCase()
    }
    for (const field of thresholds) {
      if (body[field] !== undefined) user[field] = Number(body[field]).toFixed(2)
    }
    return HttpResponse.json(toUser(user))
  }),

  http.post('/api/me/password', async ({ request }) => {
    const user = requireUser()
    const body = (await request.json()) as PasswordChangeRequest
    const weak = weakPassword(body.new_password, 'new_password')
    if (weak) return weak
    const limited = signInAttempt(user.email)
    if (limited) return limited
    if (user.password !== body.current_password) {
      return err(422, 'invalid_password', 'Current password is incorrect', {
        fields: { current_password: 'Current password is incorrect' },
      })
    }
    user.password = body.new_password
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/me/channels', async () => {
    const user = requireUser()
    await wait()
    return HttpResponse.json({
      data: store.notificationChannels.filter((c) => c.user_id === user.id).map(toNotificationChannel),
    })
  }),

  http.post('/api/me/channels', async ({ request }) => {
    const user = requireUser()
    const body = (await request.json()) as NotificationChannelCreateRequest
    if (body.kind !== 'ntfy' && body.kind !== 'webhook' && body.kind !== 'discord') {
      return err(422, 'validation_error', 'Unknown channel kind', { fields: { kind: 'Unknown channel kind' } })
    }
    // mock-parity gap: the mock instance always has a ntfy server, so the 422
    // no_server branch (ntfy kind while NTFY_SERVER_URL is unset) is backend-only
    if (store.notificationChannels.filter((c) => c.user_id === user.id).length >= MAX_CHANNELS) {
      return err(409, 'channel_limit', `You can have at most ${MAX_CHANNELS} notification channels`)
    }
    const fields = validateChannel(body.kind, body)
    if (fields instanceof HttpResponse) return fields
    const secret = body.kind === 'webhook' ? crypto.randomUUID().replace(/-/g, '') : null
    const channel = {
      id: newId(),
      user_id: user.id,
      kind: body.kind,
      secret,
      enabled: body.enabled ?? true,
      created_at: Date.now(),
      ...fields,
    }
    store.notificationChannels.push(channel)
    // the one response the signing secret ever rides in
    return HttpResponse.json({ ...toNotificationChannel(channel), secret }, { status: 201 })
  }),

  http.patch('/api/me/channels/:id', async ({ params, request }) => {
    const user = requireUser()
    const channel = store.notificationChannels.find(
      (c) => c.id === Number(params.id) && c.user_id === user.id,
    )
    if (!channel) return err(404, 'not_found', `Channel ${params.id} does not exist`)
    const body = (await request.json()) as NotificationChannelUpdateRequest
    const fields = validateChannel(channel.kind, body, channel)
    if (fields instanceof HttpResponse) return fields
    Object.assign(channel, fields)
    if (body.enabled !== undefined) channel.enabled = body.enabled
    return HttpResponse.json(toNotificationChannel(channel))
  }),

  http.delete('/api/me/channels/:id', async ({ params }) => {
    const user = requireUser()
    const id = Number(params.id)
    const channel = store.notificationChannels.find((c) => c.id === id && c.user_id === user.id)
    if (!channel) return err(404, 'not_found', `Channel ${id} does not exist`)
    store.notificationChannels = store.notificationChannels.filter((c) => c.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  // mock-parity gap: the mock sends nothing, so the 502 channel_failed of a
  // destination that refuses the test is backend-only — as is no_server
  http.post('/api/me/channels/test', async ({ request }) => {
    requireUser()
    await wait()
    const body = (await request.json()) as NotificationChannelTestRequest
    if (body.kind !== 'ntfy' && body.kind !== 'webhook' && body.kind !== 'discord') {
      return err(422, 'validation_error', 'Unknown channel kind', { fields: { kind: 'Unknown channel kind' } })
    }
    const destination = validateDestination(body.kind, body.url?.trim() || null, body.topic?.trim() || null)
    if (destination instanceof HttpResponse) return destination
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/me/channels/:id/test', async ({ params }) => {
    const user = requireUser()
    await wait()
    const channel = store.notificationChannels.find(
      (c) => c.id === Number(params.id) && c.user_id === user.id,
    )
    if (!channel) return err(404, 'not_found', `Channel ${params.id} does not exist`)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/me/tokens', async () => {
    const user = requireUser()
    await wait()
    return HttpResponse.json({
      data: store.tokens.filter((t) => t.user_id === user.id).map(toApiToken),
    })
  }),

  http.post('/api/me/tokens', async ({ request }) => {
    const user = requireUser()
    const body = (await request.json()) as ApiTokenCreateRequest
    const fields: Record<string, string> = {}
    const name = (body.name ?? '').trim()
    if (!name) fields.name = 'Name is required'
    else if (name.length > 64) fields.name = 'Must be 64 characters or fewer'
    const scopes = body.scopes ?? []
    if (scopes.length === 0) fields.scopes = 'Pick at least one scope'
    else if (scopes.some((s) => !TOKEN_SCOPES.includes(s))) fields.scopes = 'Unknown scope'
    if (body.expires_in_days != null && body.expires_in_days < 1) {
      fields.expires_in_days = 'Must be at least 1 day'
    } else if (body.expires_in_days != null && body.expires_in_days > 3650) {
      fields.expires_in_days = 'Must be 3650 days or fewer'
    }
    if (Object.keys(fields).length > 0) {
      return err(422, 'validation_error', 'Check the token details', { fields })
    }
    const token = {
      id: newId(),
      user_id: user.id,
      name,
      // canonical order, whatever order the client sent them in
      scopes: TOKEN_SCOPES.filter((s) => scopes.includes(s)),
      expires_at: body.expires_in_days != null ? Date.now() + body.expires_in_days * DAY : null,
      last_used_at: null,
      created_at: Date.now(),
    }
    store.tokens.push(token)
    // the one response the raw token ever rides in
    const raw = `snagr_pat_${crypto.randomUUID().replace(/-/g, '')}`
    return HttpResponse.json({ ...toApiToken(token), token: raw }, { status: 201 })
  }),

  http.delete('/api/me/tokens/:id', async ({ params }) => {
    const user = requireUser()
    const id = Number(params.id)
    const token = store.tokens.find((t) => t.id === id && t.user_id === user.id)
    if (!token) return err(404, 'not_found', `Token ${id} does not exist`)
    store.tokens = store.tokens.filter((t) => t.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/categories', async () => {
    requireUser()
    await wait()
    return HttpResponse.json({ data: store.categories.map(toCategory) })
  }),

  http.post('/api/categories', async ({ request }) => {
    requireAdmin()
    const body = (await request.json()) as CategoryCreateRequest
    const name = checkedName(store.categories, 'category', body.name ?? '')
    if (name instanceof HttpResponse) return name
    const category = { id: newId(), name, slug: uniqueSlug(name), site_ids: [] }
    store.categories.push(category)
    return HttpResponse.json(toCategory(category), { status: 201 })
  }),

  http.patch('/api/categories/:id', async ({ params, request }) => {
    requireAdmin()
    const category = store.categories.find((c) => c.id === Number(params.id))
    if (!category) return err(404, 'not_found', `Category ${params.id} does not exist`)
    const body = (await request.json()) as CategoryUpdateRequest
    // the slug is set once at creation and survives every rename, so links and
    // bookmarks to /categories/<slug> keep working
    if (body.name != null) {
      const name = checkedName(store.categories, 'category', body.name, category.id)
      if (name instanceof HttpResponse) return name
      category.name = name
    }
    return HttpResponse.json(toCategory(category))
  }),

  http.delete('/api/categories/:id', async ({ params }) => {
    requireAdmin()
    const id = Number(params.id)
    const itemIds = new Set(store.items.filter((i) => i.category_id === id).map((i) => i.id))
    store.categories = store.categories.filter((c) => c.id !== id)
    store.items = store.items.filter((i) => !itemIds.has(i.id))
    store.watches = store.watches.filter((w) => !itemIds.has(w.item_id))
    const listingIds = new Set(store.listings.filter((l) => itemIds.has(l.item_id)).map((l) => l.id))
    store.listings = store.listings.filter((l) => !listingIds.has(l.id))
    store.checks = store.checks.filter((c) => !listingIds.has(c.listing_id))
    // deleting an item deletes its entire vision library, so none of it
    // outlives the item
    store.references = store.references.filter((r) => !itemIds.has(r.item_id))
    store.visionQueue = store.visionQueue.filter((q) => !itemIds.has(q.item_id))
    return new HttpResponse(null, { status: 204 })
  }),

  http.put('/api/categories/:id/sites', async ({ params, request }) => {
    requireAdmin()
    const category = store.categories.find((c) => c.id === Number(params.id))
    if (!category) return err(404, 'not_found', `Category ${params.id} does not exist`)
    const body = (await request.json()) as { site_ids: number[] }
    category.site_ids = body.site_ids.filter((id) => store.sites.some((s) => s.id === id))
    return HttpResponse.json(toCategory(category))
  }),

  http.get('/api/sites', async () => {
    requireUser()
    await wait()
    return HttpResponse.json({ data: store.sites.map(toSite) })
  }),

  http.post('/api/sites', async ({ request }) => {
    requireAdmin()
    const body = (await request.json()) as SiteCreateRequest
    if (!body.name?.trim() || !body.base_url?.trim()) {
      return err(422, 'validation_error', 'Name and base URL are required')
    }
    const name = checkedName(store.sites, 'site', body.name)
    if (name instanceof HttpResponse) return name
    const site = {
      id: newId(),
      name,
      base_url: body.base_url.trim().replace(/\/$/, ''),
      paused_until: null,
      paused_reason: null,
      created_at: Date.now(),
    }
    store.sites.push(site)
    return HttpResponse.json(toSite(site), { status: 201 })
  }),

  http.patch('/api/sites/:id', async ({ params, request }) => {
    requireAdmin()
    const site = store.sites.find((s) => s.id === Number(params.id))
    if (!site) return err(404, 'not_found', `Site ${params.id} does not exist`)
    const body = (await request.json()) as SiteUpdateRequest
    // the hunter sets pauses; a person can only lift one, so null is the only
    // value this field accepts — and lifting it clears the error counter too
    if ('paused_until' in body && body.paused_until !== null) {
      return err(422, 'validation_error', 'only null is accepted; the hunter sets pauses', {
        fields: { paused_until: 'only null is accepted; the hunter sets pauses' },
      })
    }
    // "" is "leave it"; what trims to nothing is a blank, not a no-op
    if (body.name) {
      const name = checkedName(store.sites, 'site', body.name, site.id)
      if (name instanceof HttpResponse) return name
      site.name = name
    }
    if (body.base_url) {
      const baseUrl = body.base_url.trim().replace(/\/$/, '')
      if (!baseUrl) {
        return err(422, 'validation_error', 'Base URL is required', { fields: { base_url: 'Base URL is required' } })
      }
      site.base_url = baseUrl
    }
    if ('paused_until' in body) {
      site.paused_until = null
      site.paused_reason = null
      for (const job of store.jobs) {
        if (job.site_id === site.id && job.status === 'pending' && job.reason === 'paused') {
          job.run_after = Date.now()
          job.reason = 'sweep'
        }
      }
    }
    return HttpResponse.json(toSite(site))
  }),

  http.delete('/api/sites/:id', async ({ params }) => {
    requireAdmin()
    const id = Number(params.id)
    store.sites = store.sites.filter((s) => s.id !== id)
    for (const category of store.categories) {
      category.site_ids = category.site_ids.filter((sid) => sid !== id)
    }
    // an item left pinning no site follows its category again, the site_ids rule
    for (const item of store.items) {
      if (item.site_ids == null) continue
      const pinned = item.site_ids.filter((sid) => sid !== id)
      item.site_ids = pinned.length > 0 ? pinned : null
    }
    // a listing can't outlive its site, so it goes with its price history
    const listingIds = new Set(store.listings.filter((l) => l.site_id === id).map((l) => l.id))
    store.listings = store.listings.filter((l) => !listingIds.has(l.id))
    store.checks = store.checks.filter((c) => !listingIds.has(c.listing_id))
    return new HttpResponse(null, { status: 204 })
  }),

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
    const user = requireUser()
    const body = (await request.json()) as ItemCreateRequest
    if (!body.name?.trim()) {
      return err(422, 'validation_error', 'Name is required', { fields: { name: 'Name is required' } })
    }
    const category = store.categories.find((c) => c.id === body.category_id)
    if (!category) {
      return err(404, 'not_found', `Category ${body.category_id} does not exist`)
    }
    // every mock item is one the demo user tracks, so a name already in the
    // category (ignoring case) is always theirs: the backend's 422 duplicate
    if (trackedName(body.category_id, body.name)) return alreadyTracked()
    const tracking = validateTracking(body, category)
    if (tracking instanceof HttpResponse) return tracking
    const target_cents = parseTarget(body.target_price)
    if (target_cents instanceof HttpResponse) return target_cents
    const item = {
      id: newId(),
      category_id: body.category_id,
      name: body.name.trim(),
      target_cents,
      criteria: tracking.criteria,
      selection_mode: tracking.selection_mode,
      max_listings: tracking.max_listings,
      allow_reproductions: tracking.allow_reproductions,
      recheck_interval_minutes: tracking.recheck_interval_minutes,
      hunt: tracking.hunt,
      site_ids: tracking.site_ids,
      created_at: Date.now(),
    }
    store.items.push(item)
    const watch = { id: newId(), item_id: item.id, user_id: user.id, notify: true, target_cents: null }
    store.watches.push(watch)
    // a new watch starts hunting at once — one job per site it will search,
    // plus the market-price grounding the scan prompts read from. Hunting off
    // (for the watch, or for the instance) queues no hunt: creating it is not
    // a press of Hunt now.
    if (tracking.hunt && HUNT_ENABLED) {
      for (const [index, siteId] of (tracking.site_ids ?? category.site_ids).entries()) {
        enqueueHunt(watch.id, item.id, siteId, {
          user_id: user.id,
          reason: 'created',
          priority: sitePriority(index),
        })
      }
    }
    store.jobs.push(newJob('ground', { item_id: item.id, user_id: user.id, reason: 'created' }))
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
    if (body.name !== undefined) {
      if (!body.name.trim()) {
        return err(422, 'validation_error', 'Name is required', { fields: { name: 'Name is required' } })
      }
      const clash = trackedName(item.category_id, body.name)
      if (clash && clash.id !== item.id) return alreadyTracked()
    }
    const category = store.categories.find((c) => c.id === item.category_id)!
    const tracking = validateTracking(body, category, item)
    if (tracking instanceof HttpResponse) return tracking
    const target_cents = parseTarget(body.target_price)
    if (target_cents instanceof HttpResponse) return target_cents
    const roomBefore = item.max_listings
    const huntingBefore = item.hunt ?? true
    if (body.name !== undefined) item.name = body.name.trim()
    if (body.target_price !== undefined) item.target_cents = target_cents
    item.criteria = tracking.criteria
    item.selection_mode = tracking.selection_mode
    item.max_listings = tracking.max_listings
    item.allow_reproductions = tracking.allow_reproductions
    item.recheck_interval_minutes = tracking.recheck_interval_minutes
    // switching hunting off drops every waiting hunt but a pending "hunt now"
    // — the created ones carry the creator's id, but were no press
    if (huntingBefore && !tracking.hunt) {
      for (const job of store.jobs) {
        if (job.kind !== 'hunt' || job.item_id !== item.id || job.status !== 'pending') continue
        if (job.reason === 'user') continue
        job.status = 'cancelled'
        job.finished_at = Date.now()
      }
    }
    item.hunt = tracking.hunt
    item.site_ids = tracking.site_ids
    // more room, or hunting back on, is a reason to look now rather than at
    // the hunter's next hourly sweep
    if (item.hunt && (!huntingBefore || item.max_listings > roomBefore)) {
      const watch = store.watches.find((w) => w.item_id === item.id)!
      wakeHunts(watch.id, item.id, 'sweep')
    }
    // a shorter interval brings pending checks forward; a longer one is picked
    // up by the successors. Checks on a paused site stay behind the pause, and
    // only tracked listings' checks move.
    const due = Date.now() + effectiveInterval(item) * MINUTE
    for (const job of store.jobs) {
      const site = store.sites.find((s) => s.id === job.site_id)
      const paused = site?.paused_until != null && site.paused_until > Date.now()
      const tracked = store.listings.some((l) => l.id === job.listing_id && l.active)
      const pulled =
        job.kind === 'recheck' && job.item_id === item.id && job.status === 'pending' && job.run_after > due
      if (pulled && tracked && !paused) job.run_after = due
    }
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
    // deleting an item deletes its entire vision library, so none of it
    // outlives the item
    store.references = store.references.filter((r) => r.item_id !== id)
    store.visionQueue = store.visionQueue.filter((q) => q.item_id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.patch('/api/items/:id/watch', async ({ params, request }) => {
    requireUser()
    const watch = store.watches.find((w) => w.item_id === Number(params.id))
    if (!watch) return err(404, 'not_found', `Item ${params.id} does not exist`)
    const body = (await request.json()) as WatchUpdateRequest
    const target_cents = parseTarget(body.target_price)
    if (target_cents instanceof HttpResponse) return target_cents
    if (body.notify !== undefined) watch.notify = body.notify
    if (body.target_price !== undefined) watch.target_cents = target_cents
    return HttpResponse.json({ id: watch.id, notify: watch.notify, target_price: cents(watch.target_cents) })
  }),

  http.patch('/api/listings/:id', async ({ params, request }) => {
    requireUser()
    const listing = store.listings.find((l) => l.id === Number(params.id))
    if (!listing) return err(404, 'not_found', `Listing ${params.id} does not exist`)
    const body = (await request.json()) as ListingUpdateRequest
    listing.active = body.active
    // an untracked listing is not re-read; tracking it again puts it back in
    // the queue, because one pending recheck per active listing is the rule
    const pending = store.jobs.find(
      (j) => j.kind === 'recheck' && j.listing_id === listing.id && j.status === 'pending',
    )
    if (!body.active) {
      if (pending) {
        pending.status = 'cancelled'
        pending.finished_at = Date.now()
      }
      // the slot it held wakes the watch's hunts
      const watch = store.watches.find((w) => w.item_id === listing.item_id)!
      wakeHunts(watch.id, listing.item_id)
    } else if (!pending) {
      const watch = store.watches.find((w) => w.item_id === listing.item_id)!
      store.jobs.push(
        newJob('recheck', {
          watch_id: watch.id,
          item_id: listing.item_id,
          site_id: listing.site_id,
          listing_id: listing.id,
        }),
      )
    }
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
          method: c.method,
          confirmed: c.confirmed,
          checked_at: new Date(c.ts).toISOString(),
        }
      })
    return HttpResponse.json({ data: checks })
  }),

  // Contract gap, called out per house rules: this mock always reports
  // vision_enabled: true and cannot exercise the disabled mode. The real
  // backend answers 503 { error: { code: 'vision_unavailable' } } for every
  // vision MUTATION when the sidecar is unconfigured (the two GET list
  // routes return empty data instead) — covered by backend tests only.

  http.get('/api/vision/review-queue', async ({ request }) => {
    const user = requireUser()
    await wait()
    const itemId = new URL(request.url).searchParams.get('item_id')
    const page = intParam(request, 'page', 1)
    const perPage = intParam(request, 'per_page', 25)
    // scoped to the capturing watch's owner — admins included: you review
    // what YOUR hunts captured
    let entries = store.visionQueue
      .filter((e) => e.user_id === user.id && e.review_state === 'suggested')
      .sort((a, b) => b.created_at - a.created_at)
    if (itemId) entries = entries.filter((e) => e.item_id === Number(itemId))
    const total = entries.length
    entries = entries.slice((page - 1) * perPage, page * perPage)
    return HttpResponse.json({
      data: entries.map(toQueueEntry),
      meta: { page, per_page: perPage, total },
    })
  }),

  http.post('/api/vision/review-queue/:id/confirm', async ({ params, request }) => {
    const user = requireUser()
    const entry = store.visionQueue.find((e) => e.id === Number(params.id))
    // hidden ≡ nonexistent: another user's entry 404s exactly like an unknown id
    if (!entry || entry.user_id !== user.id) {
      return err(404, 'not_found', `Review entry ${params.id} does not exist`)
    }
    const body = (await request.json()) as ReviewConfirmRequest
    if (body.label !== 'real' && body.label !== 'fake') {
      return err(422, 'validation_error', 'Invalid label', {
        fields: { label: "Must be 'real' or 'fake'" },
      })
    }
    if (entry.review_state !== 'suggested') {
      return err(409, 'already_reviewed', 'This entry has already been reviewed')
    }
    const reference = {
      id: newId(),
      item_id: entry.item_id,
      label: body.label,
      variant_tag: body.variant_tag?.trim() || null,
      provenance: 'human' as const,
      object_key: entry.object_key,
      source_listing_url: entry.listing_url,
      captured_by: user.id,
      revoked: false,
      created_at: Date.now(),
    }
    store.references.push(reference)
    entry.review_state = 'confirmed'
    return HttpResponse.json(toReference(reference, user), { status: 201 })
  }),

  http.delete('/api/vision/review-queue/:id', async ({ params }) => {
    const user = requireUser()
    const entry = store.visionQueue.find((e) => e.id === Number(params.id))
    // an already-reviewed entry has left the queue — discarding it 404s too
    if (!entry || entry.user_id !== user.id || entry.review_state !== 'suggested') {
      return err(404, 'not_found', `Review entry ${params.id} does not exist`)
    }
    store.visionQueue = store.visionQueue.filter((e) => e.id !== entry.id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.get('/api/items/:id/references', async ({ params }) => {
    const user = requireUser()
    await wait()
    const id = Number(params.id)
    // items are the viewer's watches (getItem scoping): no watch → 404
    const watched = store.watches.some((w) => w.item_id === id && w.user_id === user.id)
    if (!store.items.some((i) => i.id === id) || !watched) {
      return err(404, 'not_found', `Item ${params.id} does not exist`)
    }
    const references = store.references
      .filter((r) => r.item_id === id)
      .sort((a, b) => b.created_at - a.created_at)
    return HttpResponse.json({ data: references.map((r) => toReference(r, user)) })
  }),

  http.post('/api/items/:id/references', async ({ params, request }) => {
    const user = requireUser()
    const id = Number(params.id)
    const watched = store.watches.some((w) => w.item_id === id && w.user_id === user.id)
    if (!store.items.some((i) => i.id === id) || !watched) {
      return err(404, 'not_found', `Item ${params.id} does not exist`)
    }
    const form = await request.formData()
    const file = form.get('file')
    const rawLabel = form.get('label')
    const variantTag = form.get('variant_tag')
    const label: 'real' | 'fake' | null =
      rawLabel === 'real' || rawLabel === 'fake' ? rawLabel : null
    if (!label) {
      return err(422, 'validation_error', 'Invalid label', {
        fields: { label: "Must be 'real' or 'fake'" },
      })
    }
    if (!(file instanceof File) || !file.type.startsWith('image/')) {
      return err(422, 'validation_error', 'Upload must be an image file', {
        fields: { file: 'Must be an image file' },
      })
    }
    if (file.size > 10 * 1024 * 1024) {
      return err(422, 'validation_error', 'Image must be 10 MB or smaller', {
        fields: { file: 'Must be 10 MB or smaller' },
      })
    }
    const reference = {
      id: newId(),
      item_id: id,
      label,
      variant_tag: typeof variantTag === 'string' && variantTag.trim() ? variantTag.trim() : null,
      provenance: 'upload' as const,
      object_key: `upload-${newId()}`,
      source_listing_url: null,
      captured_by: user.id,
      revoked: false,
      created_at: Date.now(),
    }
    store.references.push(reference)
    return HttpResponse.json(toReference(reference, user), { status: 201 })
  }),

  http.delete('/api/vision/references/:id', async ({ params }) => {
    const user = requireUser()
    const reference = store.references.find((r) => r.id === Number(params.id))
    // references are communal per item, so visibility = watching the item
    const visible =
      reference && store.watches.some((w) => w.item_id === reference.item_id && w.user_id === user.id)
    if (!reference || !visible) {
      return err(404, 'not_found', `Reference ${params.id} does not exist`)
    }
    // revoking an already-revoked reference is a harmless no-op
    reference.revoked = true
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/items/:id/references/revoke-auto', async ({ params }) => {
    const user = requireUser()
    const id = Number(params.id)
    const watched = store.watches.some((w) => w.item_id === id && w.user_id === user.id)
    if (!store.items.some((i) => i.id === id) || !watched) {
      return err(404, 'not_found', `Item ${params.id} does not exist`)
    }
    const autos = store.references.filter((r) => r.item_id === id && r.provenance === 'auto' && !r.revoked)
    for (const reference of autos) reference.revoked = true
    return HttpResponse.json({ revoked: autos.length })
  }),

  // bytes for <img src> — not in endpoints.ts (same precedent as the SSE
  // stream); the mock draws a deterministic placeholder per key
  http.get('/api/vision/images/:key', async ({ params }) => {
    const key = String(params.key)
    const hue = [...key].reduce((sum, ch) => sum + ch.charCodeAt(0), 0) % 360
    const svg =
      `<svg xmlns="http://www.w3.org/2000/svg" width="320" height="240">` +
      `<rect width="320" height="240" fill="hsl(${hue} 40% 22%)"/>` +
      `<text x="160" y="128" text-anchor="middle" fill="hsl(${hue} 60% 70%)" ` +
      `font-family="monospace" font-size="14">${key.slice(0, 12)}</text></svg>`
    return new HttpResponse(svg, { headers: { 'Content-Type': 'image/svg+xml' } })
  }),

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

  http.post('/api/jobs', async ({ request }) => {
    const user = requireUser()
    const body = (await request.json()) as JobCreateRequest
    const fields: Record<string, string> = {}
    if (!JOB_KINDS.includes(body.kind)) fields.kind = 'Ask for a hunt or a recheck'
    if (!JOB_SCOPES.includes(body.scope)) fields.scope = 'Unknown scope'
    else if (body.scope !== 'global' && body.scope_id == null) {
      fields.scope_id = 'Required unless the scope is global'
    }
    if (Object.keys(fields).length > 0) {
      return err(422, 'validation_error', 'Check the job request', { fields })
    }
    // the operator's kill switch: nothing would claim a hunt, so none is queued
    if (body.kind === 'hunt' && !HUNT_ENABLED) {
      return err(409, 'hunting_disabled', 'Hunting is turned off on this server')
    }

    const scopeId = body.scope === 'global' ? null : (body.scope_id ?? null)
    const watches = scopedWatches(user, body.scope, scopeId)
    // an unknown target and one holding none of the caller's watches are the
    // same 404: neither is anything this caller can ask the hunter about
    if (watches == null || watches.length === 0) {
      const action = body.kind === 'hunt' ? 'hunt for' : 'check prices for'
      return err(404, 'not_found', `You have no items here to ${action}`)
    }

    const queued: MockJob[] = []
    if (body.kind === 'hunt') {
      for (const watch of watches) {
        const sites = sitesOf(watch.item_id).filter((id) => body.scope !== 'site' || id === scopeId)
        const item = store.items.find((i) => i.id === watch.item_id)!
        // a full watch still gets a person's hunt: a swap hunt, for something
        // better than its weakest listing
        const full = activeListings(item.id).length >= item.max_listings
        for (const [index, siteId] of sites.entries()) {
          const job = enqueueHunt(watch.id, watch.item_id, siteId, {
            user_id: user.id,
            reason: 'user',
            priority: sitePriority(index),
            payload: full ? { swap: true } : null,
          })
          if (job) queued.push(job)
        }
      }
      // the demo plays the first couple; the rest wait their turn, exactly as
      // they would behind HUNT_CONCURRENCY
      for (const job of queued.filter((j) => j.status === 'pending').slice(0, 2)) startDemoHunt(job)
    } else {
      const items = new Set(watches.map((w) => w.item_id))
      for (const job of store.jobs) {
        if (job.kind !== 'recheck' || job.status !== 'pending') continue
        if (!items.has(job.item_id!)) continue
        if (body.scope === 'site' && job.site_id !== scopeId) continue
        const listing = store.listings.find((l) => l.id === job.listing_id)
        if (!listing?.active) continue
        job.run_after = Date.now()
        job.priority = 100
        queued.push(job)
      }
    }
    // an empty data is still a 202 — a watch with no site to search asks nothing
    return HttpResponse.json({ data: queued.map(toJob) }, { status: 202 })
  }),

  http.get('/api/jobs', async ({ request }) => {
    const user = requireUser()
    await wait()
    const url = new URL(request.url)
    const kinds = url.searchParams.get('kind')?.split(',').filter(Boolean)
    const statuses = url.searchParams.get('status')?.split(',').filter(Boolean)
    const itemId = url.searchParams.get('item_id')
    const page = intParam(request, 'page', 1)
    const perPage = Math.min(intParam(request, 'per_page', 20), 100)

    let jobs = store.jobs.filter((j) => jobVisible(j, user))
    if (kinds?.length) jobs = jobs.filter((j) => kinds.includes(j.kind))
    if (statuses?.length) jobs = jobs.filter((j) => statuses.includes(j.status))
    if (itemId) jobs = jobs.filter((j) => j.item_id === Number(itemId))
    // the queue reads forwards, history backwards
    jobs =
      statuses?.length === 1 && statuses[0] === 'pending'
        ? [...jobs].sort((a, b) => a.run_after - b.run_after || a.id - b.id)
        : [...jobs].sort((a, b) => b.created_at - a.created_at || b.id - a.id)

    const total = jobs.length
    jobs = jobs.slice((page - 1) * perPage, page * perPage)
    return HttpResponse.json({ data: jobs.map(toJob), meta: { page, per_page: perPage, total } })
  }),

  http.get('/api/jobs/summary', async () => {
    const user = requireUser()
    const mine = store.jobs.filter((j) => jobVisible(j, user))
    const hunts = mine.filter((j) => j.kind === 'hunt')
    const checks = mine.filter((j) => j.kind === 'recheck')
    const pendingChecks = checks.filter((j) => j.status === 'pending')
    const pendingHunts = mine.filter(
      (j) => j.status === 'pending' && (j.kind === 'hunt' || j.kind === 'ground'),
    )
    // the hunter doesn't claim a paused site's jobs, so they come due when the pause lifts
    const dueAt = (j: MockJob) => {
      const pausedUntil = store.sites.find((s) => s.id === j.site_id)?.paused_until
      return pausedUntil != null && pausedUntil > Date.now()
        ? Math.max(j.run_after, pausedUntil)
        : j.run_after
    }
    const midnight = new Date()
    midnight.setHours(0, 0, 0, 0)
    const finishedHunts = hunts
      .filter((j) => j.finished_at != null)
      .sort((a, b) => b.finished_at! - a.finished_at!)
    const watched = store.watches
      .filter((w) => w.user_id === user.id)
      .reduce((n, w) => n + activeListings(w.item_id).length, 0)

    return HttpResponse.json({
      hunts_running: hunts.filter((j) => j.status === 'running').length,
      checks_running: checks.filter((j) => j.status === 'running').length,
      checks_pending: pendingChecks.length,
      next_check_at: pendingChecks.length
        ? new Date(Math.min(...pendingChecks.map(dueAt))).toISOString()
        : null,
      next_hunt_at: pendingHunts.length
        ? new Date(Math.min(...pendingHunts.map(dueAt))).toISOString()
        : null,
      hunts_today: finishedHunts.filter((j) => j.finished_at! >= midnight.getTime()).length,
      listings_watched: watched,
      last_hunt: finishedHunts[0] ? toJob(finishedHunts[0]) : null,
      // sites are shared, so a pause is everyone's news
      paused_sites: store.sites
        .filter((s) => s.paused_until != null && s.paused_until > Date.now())
        .map((s) => ({
          site_id: s.id,
          site_name: s.name,
          paused_until: new Date(s.paused_until!).toISOString(),
          paused_reason: s.paused_reason ?? '',
        })),
    })
  }),

  http.get('/api/jobs/:id', async ({ params }) => {
    const user = requireUser()
    const job = store.jobs.find((j) => j.id === Number(params.id))
    // hidden = nonexistent: another user's job 404s exactly like an unknown id
    if (!job || !jobVisible(job, user)) {
      return err(404, 'not_found', `Job ${params.id} does not exist`)
    }
    return HttpResponse.json(toJob(job))
  }),

  http.get('/api/jobs/:id/events', async ({ params, request }) => {
    const user = requireUser()
    const job = store.jobs.find((j) => j.id === Number(params.id))
    if (!job || !jobVisible(job, user)) {
      return err(404, 'not_found', `Job ${params.id} does not exist`)
    }
    const afterSeq = intParam(request, 'after_seq', 0)
    const limit = intParam(request, 'limit', 200)
    if (limit > 500) {
      return err(422, 'validation_error', 'limit must be 500 or less', {
        fields: { limit: 'limit must be 500 or less' },
      })
    }
    // a recheck writes no events at all — its result is its price check
    const events = store.jobEvents
      .filter((e) => e.job_id === job.id && e.seq > afterSeq)
      .sort((a, b) => a.seq - b.seq)
      .slice(0, limit)
    return HttpResponse.json({ data: events.map(toJobEvent) })
  }),

  http.post('/api/jobs/:id/cancel', async ({ params }) => {
    const user = requireUser()
    const job = store.jobs.find((j) => j.id === Number(params.id))
    if (!job || !jobVisible(job, user)) {
      return err(404, 'not_found', `Job ${params.id} does not exist`)
    }
    // permission before state: "you may never cancel this" holds regardless of
    // status. A job with no watch of the caller's behind it is the hunter's own.
    const owns = store.watches.some((w) => w.id === job.watch_id && w.user_id === user.id)
    if (!owns && user.role !== 'admin') {
      return err(403, 'forbidden', 'Only an admin can cancel a system job')
    }
    if (job.kind === 'recheck') {
      return err(422, 'validation_error', 'checks finish in seconds and cannot be cancelled')
    }
    if (job.status !== 'pending' && job.status !== 'running') {
      return err(409, 'job_finished', 'This job has already finished')
    }
    cancelDemoHunt(job)
    return HttpResponse.json(toJob(job))
  }),

  http.get('/api/events', () => {
    const user = sessionUser()
    if (!user) return err(401, 'unauthenticated', 'Not signed in')

    let client: StreamClient
    let heartbeat: ReturnType<typeof setInterval>
    const encoder = new TextEncoder()
    const stream = new ReadableStream({
      start(controller) {
        client = {
          user,
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
    const losesAdmin =
      user.role === 'admin' &&
      user.is_active &&
      ((body.role !== undefined && body.role !== 'admin') || body.is_active === false)
    if (losesAdmin && !store.users.some((u) => u.id !== user.id && u.role === 'admin' && u.is_active)) {
      return err(409, 'last_admin', 'This is the only active admin — make someone else an admin first')
    }
    if (body.is_active !== undefined) user.is_active = body.is_active
    if (body.role !== undefined) user.role = body.role
    return HttpResponse.json(toAdminUser(user))
  }),

  http.delete('/api/admin/users/:id', async ({ params }) => {
    const admin = requireAdmin()
    const id = Number(params.id)
    if (id === admin.id) return err(422, 'cannot_delete_self', 'You cannot delete your own account')
    if (!store.users.some((u) => u.id === id)) return err(404, 'not_found', `User ${params.id} does not exist`)
    // everything that is theirs goes with them; catalog items stay, and the
    // listings and history of an item only they watched go with their watch
    const theirs = store.watches.filter((w) => w.user_id === id)
    const watchIds = new Set(theirs.map((w) => w.id))
    store.watches = store.watches.filter((w) => w.user_id !== id)
    const orphaned = new Set(
      theirs.map((w) => w.item_id).filter((itemId) => !store.watches.some((w) => w.item_id === itemId)),
    )
    const listingIds = new Set(store.listings.filter((l) => orphaned.has(l.item_id)).map((l) => l.id))
    store.listings = store.listings.filter((l) => !listingIds.has(l.id))
    store.checks = store.checks.filter((c) => !listingIds.has(c.listing_id))
    store.jobs = store.jobs.filter((j) => j.watch_id == null || !watchIds.has(j.watch_id))
    for (const job of store.jobs) if (job.user_id === id) job.user_id = null
    store.notificationChannels = store.notificationChannels.filter((c) => c.user_id !== id)
    store.tokens = store.tokens.filter((t) => t.user_id !== id)
    store.visionQueue = store.visionQueue.filter((q) => q.user_id !== id)
    store.users = store.users.filter((u) => u.id !== id)
    return new HttpResponse(null, { status: 204 })
  }),

  http.post('/api/admin/users/:id/password-reset', async ({ params }) => {
    requireAdmin()
    const id = Number(params.id)
    if (!store.users.some((u) => u.id === id)) return err(404, 'not_found', `User ${params.id} does not exist`)
    // a new link replaces any earlier one, so only the newest works
    store.passwordResets = store.passwordResets.filter((r) => r.user_id !== id)
    const reset = {
      token: crypto.randomUUID().replace(/-/g, ''),
      user_id: id,
      expires_at: Date.now() + DAY,
      used_at: null,
    }
    store.passwordResets.push(reset)
    return HttpResponse.json({ token: reset.token, expires_at: new Date(reset.expires_at).toISOString() }, { status: 201 })
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
      email: body.email?.trim().toLowerCase() || null,
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
