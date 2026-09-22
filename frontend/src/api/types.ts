/**
 * TypeScript mirror of the Snagr API contract.
 * This file IS the contract — the backend's Pydantic schemas mirror it field-for-field.
 *
 * Conventions:
 * - Prices are decimal strings ("549.99"), never floats.
 * - Timestamps are ISO-8601 UTC strings.
 * - Errors use the envelope { error: { code, message, fields? } }.
 * - Paginated lists use { data: [...], meta: { page, per_page, total } }.
 */

import type { TimeRange } from '@/lib/time'

// ---------------------------------------------------------------------------
// Shared

export interface PageMeta {
  page: number
  per_page: number
  total: number
}

export interface Paginated<T> {
  data: T[]
  meta: PageMeta
}

export interface ApiErrorBody {
  error: {
    code: string
    message: string
    fields?: Record<string, string>
  }
}

// ---------------------------------------------------------------------------
// Instance / auth

export interface InstanceInfo {
  version: string
  /** the ntfy server notifications are pushed through, shown in the ntfy
   *  channel form; null when the admin hasn't configured NTFY_SERVER_URL */
  ntfy_server_url: string | null
  /** true only while the instance has zero users (first-admin bootstrap) */
  registration_open: boolean
  /** SSO login-button label (e.g. "Authentik"); null when OIDC is not configured */
  oidc_provider_name: string | null
  /** true when the operator has configured the vision sidecar (VISION_SIDECAR_URL) */
  vision_enabled: boolean
  /** false when the operator turned agent access off (MCP_ENABLED): no MCP endpoint,
   *  no bearer auth, and Settings hides the MCP & API tab */
  mcp_enabled: boolean
}

export type UserRole = 'admin' | 'user'

export interface User {
  id: number
  email: string
  role: UserRole
  /**
   * Vision thresholds (0–1 decimal strings, always resolved — never null).
   * auto_reject_fake: fake confidence at/above this auto-rejects a listing;
   * auto_promote_*: min confidence for a suggestion to self-promote to gold.
   */
  vision_auto_reject_fake: string
  vision_auto_promote_real: string
  vision_auto_promote_fake: string
  created_at: string
}

export interface LoginRequest {
  email: string
  password: string
}

export interface RegisterRequest {
  email: string
  password: string
}

/** GET /api/auth/invites/{token} — 404 invalid, 410 expired/used */
export interface InviteValidation {
  email: string | null
  expires_at: string
}

export interface InviteAcceptRequest {
  email: string
  password: string
}

// ---------------------------------------------------------------------------
// Categories

export interface Category {
  id: number
  name: string
  slug: string
  site_ids: number[]
  item_count: number
  snagged_count: number
}

export interface CategoryCreateRequest {
  name: string
}

export interface CategoryUpdateRequest {
  name?: string
}

// ---------------------------------------------------------------------------
// Sites

export interface Site {
  id: number
  name: string
  base_url: string
  category_ids: number[]
  listing_count: number
  last_checked_at: string | null
  /** set by the hunter's circuit breaker; null = the site is not paused */
  paused_until: string | null
  paused_reason: string | null
  created_at: string
}

export interface SiteCreateRequest {
  name: string
  base_url: string
}

export interface SiteUpdateRequest {
  name?: string
  base_url?: string
  /** null is the ONLY accepted value: it clears the pause and the error
   *  counter. The hunter sets pauses; a person can only lift one. */
  paused_until?: null
}

// ---------------------------------------------------------------------------
// Items / listings / watches

/**
 * How an item picks which listings to track:
 * - 'cheapest'   — pure price ranking; criteria (if any) is scored for display only
 * - 'best_match' — agent ranks by criteria fit (match_score desc, price asc tiebreak)
 *                  and may leave slots empty rather than track poor matches (~score < 50)
 */
export type SelectionMode = 'cheapest' | 'best_match'

export interface Watch {
  id: number
  notify: boolean
  /** null = inherit the item's target_price */
  target_price: string | null
}

/** Row shape for item lists — includes the price rollup and sparkline. */
export interface ItemSummary {
  id: number
  name: string
  category_id: number
  category_name: string
  category_slug: string
  target_price: string | null
  currency: string
  /** free-text natural-language criteria the agent evaluates listings against */
  criteria: string | null
  selection_mode: SelectionMode
  /** how many listings to track at once (1–10) */
  max_listings: number
  /** true = skip the agent's reproduction/counterfeit screening for this item */
  allow_reproductions: boolean
  /** subset of the category's linked sites to search; null = all of them */
  site_ids: number[] | null
  best_price: string | null
  best_listing_id: number | null
  best_site_name: string | null
  avg_price: string | null
  active_listing_count: number
  target_met: boolean
  /** signed percent change of best price over the requested range, e.g. "-8.30" */
  pct_change_range: string | null
  last_checked_at: string | null
  created_at: string
  watch: Watch
  /** ≤30 bucketed best-price points over the requested range; null = no data in bucket */
  spark: (string | null)[]
}

export interface Listing {
  id: number
  site_id: number
  site_name: string
  url: string
  /** agent-extracted listing title; null until first check */
  title: string | null
  site_sku: string | null
  /**
   * Tracked = active. The agent sets active=false when a listing sells/ends
   * (its final price check carries status 'sold' | 'ended'); users can also
   * toggle it manually.
   */
  active: boolean
  latest_price: string | null
  in_stock: boolean | null
  /** status of the latest price check: 'ok' | 'sold' | 'ended' | 'error' */
  latest_status: string | null
  /** 0–100 criteria fit judged by the agent; null when never evaluated */
  match_score: number | null
  /** one-line rationale, e.g. "dry battery ✓, damaged case ✓, cart only" */
  match_summary: string | null
  /** image-based authenticity read; null = never scanned (vision off, repro
   *  allowed, or discovered before the feature) */
  authenticity: AuthenticityRead | null
  last_checked_at: string | null
  created_at: string
  /** the hunt job that saved this listing; null for rows older than jobs */
  discovered_by_job_id: number | null
}

/** What the hunter will do next for one item — computed from its jobs. */
export interface HuntFacts {
  running: boolean
  next_at: string | null
  last_at: string | null
  last_result: 'found' | 'nothing' | 'failed' | 'cancelled' | null
  slots_open: number
}

export interface RecheckFacts {
  /** how many of this item's rechecks are running right now */
  running: number
  next_at: string | null
  /** minutes between checks for this item's listings; PR 2a = the instance default */
  interval_minutes: number
}

/** Not on ItemSummary — list queries stay cheap. */
export interface ItemDetail extends ItemSummary {
  listings: Listing[]
  hunt: HuntFacts
  recheck: RecheckFacts
}

export interface ItemCreateRequest {
  category_id: number
  name: string
  target_price: string | null
  /** default null */
  criteria?: string | null
  /** default 'cheapest' */
  selection_mode?: SelectionMode
  /** default 5; 422 outside 1–10 */
  max_listings?: number
  /** default false */
  allow_reproductions?: boolean
  /** must be a subset of the category's sites (422 otherwise); empty/full set normalizes to null */
  site_ids?: number[] | null
}

export interface ItemUpdateRequest {
  name?: string
  target_price?: string | null
  criteria?: string | null
  selection_mode?: SelectionMode
  max_listings?: number
  allow_reproductions?: boolean
  site_ids?: number[] | null
}

export interface WatchUpdateRequest {
  notify?: boolean
  target_price?: string | null
}

export interface ListingUpdateRequest {
  active: boolean
}

export type ItemStatusFilter = 'all' | 'snagged' | 'above_target' | 'no_listings'

export interface ItemListParams {
  category_id?: number
  /** only items with a tracked listing on this site */
  site_id?: number
  status?: ItemStatusFilter
  search?: string
  range?: TimeRange
  sort?: string
  page?: number
  per_page?: number
}

export interface PriceCheck {
  id: number
  listing_id: number
  site_name: string
  price: string | null
  currency: string
  in_stock: boolean | null
  /** 'ok' | 'sold' | 'ended' | 'error' — 'sold'/'ended' is terminal for the listing */
  status: string | null
  /** how the price was read: 'llm' (the model looked at the page) or one of
   *  'jsonld' | 'meta' | 'microdata' | 'locator' (code replayed the listing's
   *  stored locator, no model involved). null on rows older than the column. */
  method: string | null
  /** false for a reading the plausibility bands rejected — a "$4.49" on a $449
   *  item. Still shown, because hiding an observation is its own failure, but
   *  it never notifies and never enters a chart or an average until a later
   *  read agrees with it. */
  confirmed: boolean
  checked_at: string
}

// ---------------------------------------------------------------------------
// Vision / authenticity
//
// The image-based second opinion on listing authenticity (per-item reference
// libraries scored by the vision sidecar). Verdicts are asymmetric on
// purpose: leans_fake = photos consistent with known fakes (a STRONG
// signal — scam listings reuse stolen photos of genuine items, so matching
// fakes condemns); leans_real = photos match known-real references (WEAK
// reassurance only — never present it as "verified authentic").

export type AuthenticityVerdict = 'leans_real' | 'leans_fake' | 'inconclusive'

export interface AuthenticityRead {
  /** leans_fake = photos consistent with known fakes (strong signal);
   *  leans_real = photos match known-real references (weak reassurance ONLY) */
  verdict: AuthenticityVerdict
  /** 0–1 decimal string; null when the item's library couldn't score it */
  fake_confidence: string | null
  image_count: number
  checked_at: string
}

export type ReferenceLabel = 'real' | 'fake'
export type ReferenceProvenance = 'human' | 'upload' | 'auto'
export type LlmAuthenticityRead = 'looks_authentic' | 'suspect' | 'unsure'

/** A captured listing photo awaiting the owner's confirm/discard. The queue
 *  is scoped to the capturing watch's owner — admins included (D-V11). */
export interface ReviewQueueEntry {
  id: number
  item_id: number
  item_name: string
  /** same-origin backend proxy path: /api/vision/images/{key} */
  image_url: string
  listing_url: string
  suggested_label: ReferenceLabel
  /** 0–1 decimal string backing the suggestion */
  confidence: string
  llm_authenticity_read: LlmAuthenticityRead | null
  created_at: string
}

export interface ReviewConfirmRequest {
  /** may flip the suggestion */
  label: ReferenceLabel
  variant_tag?: string | null
}

/** One gold reference in an item's communal library. */
export interface ReferenceImage {
  id: number
  item_id: number
  label: ReferenceLabel
  variant_tag: string | null
  provenance: ReferenceProvenance
  image_url: string
  /** null unless the viewer captured it or is admin (D-V11) */
  source_listing_url: string | null
  revoked: boolean
  created_at: string
}

// ---------------------------------------------------------------------------
// Chart / aggregate endpoints

export interface PricePoint {
  /** ISO timestamp */
  ts: string
  price: string
  in_stock: boolean
}

export interface ListingSeries {
  listing_id: number
  site_name: string
  title: string | null
  active: boolean
  points: PricePoint[]
}

/** GET /api/items/{id}/price-history?range&points */
export interface PriceHistoryResponse {
  item_id: number
  target_price: string | null
  currency: string
  range: TimeRange
  series: ListingSeries[]
}

export interface SummaryPoint {
  ts: string
  avg: string | null
  best: string | null
}

/** GET /api/items/{id}/price-summary?range&points */
export interface PriceSummaryResponse {
  item_id: number
  target_price: string | null
  currency: string
  range: TimeRange
  points: SummaryPoint[]
}

export interface CategoryItemChange {
  item_id: number
  name: string
  /** signed percent, e.g. "-12.40"; null when <2 prices in range */
  pct_change: string | null
  old_best: string | null
  new_best: string | null
}

/** GET /api/categories/{id}/price-change?range */
export interface CategoryPriceChangeResponse {
  category_id: number
  range: TimeRange
  items: CategoryItemChange[]
}

export interface StatTile {
  value: number
  /** vs the previous equal-length period */
  delta: number
  spark: number[]
}

/** GET /api/dashboard/stats?range */
export interface DashboardStats {
  tracked_items: StatTile
  active_listings: StatTile
  price_drops: StatTile
  snagged: StatTile
}

export interface PriceDrop {
  item_id: number
  item_name: string
  listing_id: number
  site_name: string
  old_price: string
  new_price: string
  currency: string
  /** signed percent, negative for drops */
  pct_change: string
  checked_at: string
}

// ---------------------------------------------------------------------------
// Jobs — the hunter's work queue
//
// Three kinds of work: a `hunt` searches one (watch, site) pair with the model
// and the browser, a `recheck` re-reads one known listing's price with no model
// in the loop, and a `ground` refreshes an item's market-price stats.
//
// Visibility: a caller sees jobs for their own watches, `ground` jobs for items
// they watch, and — as admin — everything. A job the caller may not see is a
// 404, never a 403 (hidden = nonexistent).

export type JobKind = 'hunt' | 'recheck' | 'ground'
export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
/** what a user may ask for; the four scopes the UI has always offered */
export type JobScope = 'global' | 'category' | 'site' | 'item'

export interface JobStats {
  /** hunt: candidates the model looked at · recheck: 1 · ground: sources read */
  listings_checked: number
  prices_found: number
  new_listings: number
  errors: number
  tokens_in: number
  tokens_out: number
  duration_ms: number | null
  /** recheck only: how the price was read — 'llm' | 'jsonld' | 'meta' | 'microdata' | 'locator' */
  method: string | null
  /** recheck only: 'static' = a plain GET, no browser · 'browser' */
  transport: 'static' | 'browser' | null
}

export interface Job {
  id: number
  kind: JobKind
  status: JobStatus
  /** who asked; null = the hunter queued it itself (scheduler) — shown as "system" */
  user_id: number | null
  watch_id: number | null
  item_id: number | null
  item_name: string | null
  site_id: number | null
  site_name: string | null
  listing_id: number | null
  /** "Game Boy Color × eBay" (hunt) · "Game Boy Color · check" (recheck) · "Game Boy Color · market price" (ground) */
  label: string
  priority: number
  /** ISO; the queue sorts pending jobs by this */
  run_after: string
  attempts: number
  started_at: string | null
  finished_at: string | null
  /** one sentence for a human, e.g. "eBay answered a challenge page instead of the listing." */
  error: string | null
  stats: JobStats | null
  /** why it was queued: 'user' | 'created' | 'slot_freed' | 'sweep' | 'paused' — the queue's grey text */
  reason: string | null
  /** highest event seq written so far (hunts and ground only; rechecks stay 0) */
  last_seq: number
  created_at: string
}

export interface JobCreateRequest {
  kind: 'hunt' | 'recheck'
  scope: JobScope
  /** required unless scope is 'global' */
  scope_id?: number
}

export interface JobListParams {
  page?: number
  per_page?: number
  /** one kind or a comma-separated list, e.g. 'hunt,ground' */
  kind?: string
  /** one status or a comma-separated list, e.g. 'done,failed,cancelled' */
  status?: string
  item_id?: number
}

/** the presence sentence, the ticker and the queue's checks line read this one object */
export interface JobsSummary {
  hunts_running: number
  checks_running: number
  checks_pending: number
  next_check_at: string | null
  next_hunt_at: string | null
  hunts_today: number
  listings_watched: number
  /** the most recent finished hunt visible to the viewer */
  last_hunt: Job | null
  paused_sites: PausedSite[]
}

export interface PausedSite {
  site_id: number
  site_name: string
  paused_until: string
  paused_reason: string
}

export type JobEventLevel = 'info' | 'success' | 'warn' | 'error'

export type JobEventType =
  | 'job_started'
  | 'listing_check'
  /** candidate scored against the item's criteria — payload: url, title, match_score, match_summary, tracked */
  | 'listing_evaluated'
  | 'price_found'
  | 'listing_discovered'
  /** tracked listing sold/ended; slot freed — payload: listing_id, item_id */
  | 'listing_ended'
  /** the breaker tripped on this job's site — payload: site_id, paused_until, paused_reason */
  | 'site_paused'
  | 'error'
  | 'job_finished'

export interface JobEvent {
  job_id: number
  seq: number
  ts: string
  level: JobEventLevel
  event_type: JobEventType
  message: string
  payload: Record<string, unknown> | null
}

/** one recheck result, as the SSE frame carries it */
export interface ListingChecked {
  listing_id: number
  item_id: number
  item_name: string
  site_name: string
  price: string | null
  currency: string
  status: string | null
  method: string | null
  confirmed: boolean
  /** true when this check ended or sold the listing and a slot opened */
  slot_freed: boolean
  checked_at: string
}

// ---------------------------------------------------------------------------
// SSE stream (GET /api/events)
//
// Named events on the stream (all delivered per-viewer — jobs the viewer may
// not see are never sent):
//   job.snapshot  → JobSnapshotData  (sent once on every connect/reconnect)
//   job.started   → { job: Job }
//   job.event     → JobEvent         (id: "<job_id>:<seq>")
//   job.finished  → { job: Job }     (stats populated)
//   job.failed    → { job: Job }     (error populated)
//   listing.checked → ListingChecked (every price check the agent writes)
// Heartbeat: comment line `: ping` every 15s.
//
// Rechecks emit no lifecycle frames and write no events: their result IS the
// listing.checked frame. Reconnect contract: on every job.snapshot, refetch
// GET /api/jobs/{id}/events?after_seq=<highest seq held> and merge by seq —
// the filtered response is authoritative. snapshot last_seq is the job's
// GLOBAL write cursor; a filtered viewer legitimately holds a sparse subset
// of seqs, so never infer missed events from seq arithmetic.

export interface JobSnapshotData {
  /** every non-terminal hunt and ground job the viewer may see */
  jobs: Job[]
}

// ---------------------------------------------------------------------------
// Settings / admin

export interface MeUpdateRequest {
  email?: string
  /** vision thresholds; 422 validation_error outside 0.50–1.00 */
  vision_auto_reject_fake?: string
  vision_auto_promote_real?: string
  vision_auto_promote_fake?: string
}

export interface PasswordChangeRequest {
  current_password: string
  new_password: string
}

export type ChannelKind = 'ntfy' | 'webhook' | 'discord'

/**
 * Events a notification channel can receive. Additive: channels with
 * events: null pick up new members of this union automatically.
 */
export type NotificationEvent = 'target.hit' | 'listing.new'

export interface NotificationChannel {
  id: number
  kind: ChannelKind
  name: string
  /** destination for webhook/discord; null for ntfy */
  url: string | null
  /** topic on the instance's ntfy server; null for other kinds */
  topic: string | null
  /** webhook only: an HMAC signing secret is stored (returned exactly once, at create) */
  has_secret: boolean
  /** events this channel receives; null = all (empty/full set normalizes to null) */
  events: NotificationEvent[] | null
  enabled: boolean
  created_at: string
}

/**
 * POST /api/me/channels response — `secret` is shown once and never again
 * (webhook kind only; null otherwise).
 */
export interface NotificationChannelCreated extends NotificationChannel {
  secret: string | null
}

/**
 * 422 validation_error (+fields): name required; url required for
 * webhook/discord (discord must be a discord.com/api/webhooks URL); topic
 * required for ntfy; events must be a subset of the known events.
 * 422 no_server: kind 'ntfy' while the instance has no ntfy server configured.
 */
export interface NotificationChannelCreateRequest {
  kind: ChannelKind
  name: string
  url?: string
  topic?: string
  events?: NotificationEvent[] | null
  /** default true */
  enabled?: boolean
}

/** kind is immutable — delete and recreate to change a channel's kind. */
export interface NotificationChannelUpdateRequest {
  name?: string
  url?: string
  topic?: string
  events?: NotificationEvent[] | null
  enabled?: boolean
}

/** read = every GET (and the SSE stream); write = mutations; jobs = queue hunts
 *  and price checks, cancel jobs */
export type ApiTokenScope = 'read' | 'write' | 'jobs'

/**
 * A personal access token — the bearer credential for the MCP endpoint and the
 * REST API (`Authorization: Bearer snagr_pat_…`). Tokens act on the domain, never
 * the account: /api/auth/*, /api/me/* and /api/admin/* answer 403 to one.
 */
export interface ApiToken {
  id: number
  name: string
  /** always in canonical order: read, write, jobs */
  scopes: ApiTokenScope[]
  /** null = never expires */
  expires_at: string | null
  /** null = never used; stamped at most once a minute */
  last_used_at: string | null
  created_at: string
}

/** POST /api/me/tokens response — `token` is shown once and never again. */
export interface ApiTokenCreated extends ApiToken {
  token: string
}

export interface ApiTokenCreateRequest {
  /** 1–64 chars; 422 validation_error with fields.name otherwise */
  name: string
  /** non-empty subset of the known scopes; 422 with fields.scopes otherwise */
  scopes: ApiTokenScope[]
  /** omit/null = never expires; 422 with fields.expires_in_days below 1 */
  expires_in_days?: number | null
}

export interface AdminUser {
  id: number
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
  item_count: number
}

export interface AdminUserUpdateRequest {
  is_active?: boolean
  role?: UserRole
}

export interface Invite {
  id: number
  token: string
  email: string | null
  expires_at: string
  created_at: string
}

export interface InviteCreateRequest {
  email?: string
}
