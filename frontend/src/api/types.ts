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

/** Pagination facts on a Paginated response; `total` counts every matching row. */
export interface PageMeta {
  page: number
  per_page: number
  total: number
}

/** Envelope for paged lists; unpaged lists are a plain `{ data: [...] }`. */
export interface Paginated<T> {
  data: T[]
  meta: PageMeta
}

/**
 * The error envelope every non-2xx response carries; `fields` maps a field
 * name to its message on 422 validation errors.
 */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    fields?: Record<string, string>
  }
}

// ---------------------------------------------------------------------------
// Instance / auth

/** GET /api/instance — what the operator configured; public, read before anyone logs in. */
export interface InstanceInfo {
  version: string
  /** the ntfy server notifications are pushed through, shown in the ntfy
   *  channel form; null when the admin hasn't configured NTFY_SERVER_URL */
  ntfy_server_url: string | null
  /** true while the instance has zero users (first-admin bootstrap) or the
   *  operator left REGISTRATION_OPEN on */
  registration_open: boolean
  /** SSO login-button label (e.g. "Authentik"); null when OIDC is not configured */
  oidc_provider_name: string | null
  /** true when the operator has configured the vision sidecar (VISION_SIDECAR_URL) */
  vision_enabled: boolean
  /** false when the operator turned agent access off (MCP_ENABLED): no MCP endpoint,
   *  no bearer auth, and Settings hides the MCP & API tab */
  mcp_enabled: boolean
  /** minutes between rechecks for a watch with no interval of its own
   *  (RECHECK_INTERVAL_MINUTES) — the item form's placeholder */
  recheck_interval_default: number
  /** false when the operator switched hunting off (HUNT_ENABLED): nothing is hunted,
   *  "hunt now" answers 409 hunting_disabled, and prices are still rechecked */
  hunt_enabled: boolean
}

/** admin can also manage users and invites, and sees every user's jobs. */
export type UserRole = 'admin' | 'user'

/** The signed-in user — GET /api/auth/me, PATCH /api/me, and `{ user }` from login/register/accept. */
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

/** POST /api/auth/login body. */
export interface LoginRequest {
  email: string
  password: string
}

/** POST /api/auth/register body. */
export interface RegisterRequest {
  email: string
  password: string
}

/** GET /api/auth/invites/{token} — 404 invalid, 410 expired/used */
export interface InviteValidation {
  email: string | null
  expires_at: string
}

/** POST /api/auth/invites/{token}/accept body; an invite pinned to an email ignores this one. */
export interface InviteAcceptRequest {
  email: string
  password: string
}

// ---------------------------------------------------------------------------
// Categories

/**
 * A category with its linked sites; `item_count` and `snagged_count` are computed
 * through the caller's watches, not stored.
 */
export interface Category {
  id: number
  name: string
  slug: string
  site_ids: number[]
  item_count: number
  snagged_count: number
}

/** POST /api/categories body. */
export interface CategoryCreateRequest {
  name: string
}

/** PATCH /api/categories/{id} body; renaming leaves the slug alone. */
export interface CategoryUpdateRequest {
  name?: string
}

// ---------------------------------------------------------------------------
// Sites

/** A retail site the hunter searches; `listing_count` and `last_checked_at` are computed. */
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

/** POST /api/sites body. */
export interface SiteCreateRequest {
  name: string
  base_url: string
}

/** PATCH /api/sites/{id} body; omitted fields are left unchanged. */
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

/** The caller's own settings on an item — ItemSummary.watch and PATCH /api/items/{id}/watch. */
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
  /** minutes between rechecks of this item's listings; null = the instance default */
  recheck_interval_minutes: number | null
  /** true = the hunter looks for new listings on its own while slots are open;
   *  false = only when someone presses Hunt now. ItemDetail carries it as hunt.enabled */
  hunt: boolean
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

/**
 * One tracked listing of an item (ItemDetail.listings); its latest_* fields come from
 * the newest price check.
 */
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
  /** the watch's own switch — ItemSummary.hunt */
  enabled: boolean
  running: boolean
  next_at: string | null
  last_at: string | null
  last_result: 'found' | 'nothing' | 'failed' | 'cancelled' | null
  slots_open: number
  /** how long the next hunt waits after the last came back empty
   *  (15 → 30 → … → 360); null = not backing off */
  backoff_minutes: number | null
}

/** When this item's listings are next rechecked — computed from its jobs, never stored. */
export interface RecheckFacts {
  /** how many of this item's rechecks are running right now */
  running: number
  next_at: string | null
  /** minutes between checks for this item's listings: the watch's own interval,
   *  else the instance default, never below the floor — what the hunter schedules by */
  interval_minutes: number
}

/** Not on ItemSummary — list queries stay cheap. `hunt` here is the facts
 *  object; the summary's boolean is its `enabled`. */
export interface ItemDetail extends Omit<ItemSummary, 'hunt'> {
  listings: Listing[]
  hunt: HuntFacts
  recheck: RecheckFacts
}

/** POST /api/items body: finds or creates the item and adds the caller's watch. */
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
  /** default null (the instance default); 422 below the instance floor
   *  (RECHECK_INTERVAL_FLOOR_MINUTES, 5 unless changed) or above 1440 */
  recheck_interval_minutes?: number | null
  /** default true; false queues no hunt on create */
  hunt?: boolean
  /** must be a subset of the category's sites (422 otherwise); empty/full set normalizes to null */
  site_ids?: number[] | null
}

/** PATCH /api/items/{id} body; omitted fields are left unchanged. */
export interface ItemUpdateRequest {
  name?: string
  target_price?: string | null
  criteria?: string | null
  selection_mode?: SelectionMode
  max_listings?: number
  allow_reproductions?: boolean
  /** the one field where null changes something: back to the instance default;
   *  omitted = unchanged. Same 422s as create */
  recheck_interval_minutes?: number | null
  /** false drops the hunts the hunter queued for itself; a pending "hunt now" still runs */
  hunt?: boolean
  site_ids?: number[] | null
}

/** PATCH /api/items/{id}/watch body; omitted fields are left unchanged. */
export interface WatchUpdateRequest {
  notify?: boolean
  target_price?: string | null
}

/** PATCH /api/listings/{id} body: stop or resume tracking a listing. */
export interface ListingUpdateRequest {
  active: boolean
}

/**
 * snagged = best price at/below target · above_target = has listings, none at target ·
 * no_listings = nothing tracked yet.
 */
export type ItemStatusFilter = 'all' | 'snagged' | 'above_target' | 'no_listings'

/** GET /api/items query filters. */
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

/** One raw price reading of a listing — GET /api/items/{id}/price-checks. */
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

/** leans_fake is a strong signal, leans_real only weak reassurance (see the note above). */
export type AuthenticityVerdict = 'leans_real' | 'leans_fake' | 'inconclusive'

/** The image-based authenticity verdict on one listing (Listing.authenticity). */
export interface AuthenticityRead {
  /** leans_fake = photos consistent with known fakes (strong signal);
   *  leans_real = photos match known-real references (weak reassurance ONLY) */
  verdict: AuthenticityVerdict
  /** 0–1 decimal string; null when the item's library couldn't score it */
  fake_confidence: string | null
  image_count: number
  checked_at: string
}

/** Which side of the library a reference photo counts for. */
export type ReferenceLabel = 'real' | 'fake'
/**
 * human = confirmed from the review queue · upload = a person uploaded it ·
 * auto = promoted on its own past the owner's threshold, vouched for by nobody.
 */
export type ReferenceProvenance = 'human' | 'upload' | 'auto'
/** The hunt model's own authenticity call on the listing, shown next to the photo. */
export type LlmAuthenticityRead = 'looks_authentic' | 'suspect' | 'unsure'

/** A captured listing photo awaiting the owner's confirm/discard. It appears only
 *  in the queue of the capturing watch's owner — admins review only their own too. */
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

/** POST /api/vision/review-queue/{id}/confirm body. */
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
  /** null unless the viewer captured it or is admin */
  source_listing_url: string | null
  revoked: boolean
  created_at: string
}

// ---------------------------------------------------------------------------
// Chart / aggregate endpoints

/** One confirmed price reading on a listing's history line. */
export interface PricePoint {
  /** ISO timestamp */
  ts: string
  price: string
  in_stock: boolean
}

/** One listing's price line in PriceHistoryResponse. */
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

/** One time bucket of PriceSummaryResponse; null prices mean no readings fell in it. */
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

/** One item's best-price movement in CategoryPriceChangeResponse. */
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

/** One dashboard counter: its value, the change, and a sparkline. */
export interface StatTile {
  value: number
  /** what it compares against differs per tile: tracked_items and active_listings
   *  count what was added since the range began, price_drops is this range vs the
   *  previous equal-length one, snagged is a placeholder (0 or 1) */
  delta: number
  /** 12 points ramping from the compared value to the current one — a shape, not history */
  spark: number[]
}

/** GET /api/dashboard/stats?range */
export interface DashboardStats {
  tracked_items: StatTile
  active_listings: StatTile
  price_drops: StatTile
  snagged: StatTile
}

/** One row of GET /api/dashboard/price-drops: a listing whose price fell between two checks. */
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

/** hunt, recheck or ground — see the section note above. */
export type JobKind = 'hunt' | 'recheck' | 'ground'
/** pending → running → done | failed | cancelled; the last three are terminal. */
export type JobStatus = 'pending' | 'running' | 'done' | 'failed' | 'cancelled'
/** what a user may queue work for: everything, or one category, site or item */
export type JobScope = 'global' | 'category' | 'site' | 'item'

/** A job's tally, written when it finishes; Job.stats is null until then. */
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

/** One unit of the hunter's queued work — the /api/jobs routes and the SSE lifecycle frames. */
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
  /** why it was queued: 'user' | 'created' | 'slot_freed' | 'sweep' | 'paused' | 'backoff'
   *  — the queue's grey text */
  reason: string | null
  /** highest event seq written so far (hunts and ground only; rechecks stay 0) */
  last_seq: number
  created_at: string
}

/** POST /api/jobs body: queue hunts or rechecks for a scope. */
export interface JobCreateRequest {
  kind: 'hunt' | 'recheck'
  scope: JobScope
  /** required unless scope is 'global' */
  scope_id?: number
}

/** GET /api/jobs query filters. */
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

/** A site the hunter's circuit breaker has paused, as JobsSummary lists it. */
export interface PausedSite {
  site_id: number
  site_name: string
  paused_until: string
  paused_reason: string
}

/** How the Activity log colours an event line. */
export type JobEventLevel = 'info' | 'success' | 'warn' | 'error'

/** What a JobEvent reports; the payload's shape depends on it. */
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

/**
 * One progress line of a hunt or ground job — GET /api/jobs/{id}/events and the
 * SSE job.event frame. `seq` orders a job's events.
 */
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

/** The job.snapshot SSE frame, sent on every connect and reconnect. */
export interface JobSnapshotData {
  /** every non-terminal hunt and ground job the viewer may see */
  jobs: Job[]
}

// ---------------------------------------------------------------------------
// Settings / admin

/** PATCH /api/me body; omitted fields are left unchanged. */
export interface MeUpdateRequest {
  email?: string
  /** vision thresholds; 422 validation_error outside 0.50–1.00 */
  vision_auto_reject_fake?: string
  vision_auto_promote_real?: string
  vision_auto_promote_fake?: string
}

/** POST /api/me/password body. */
export interface PasswordChangeRequest {
  current_password: string
  new_password: string
}

/** Where a notification channel delivers. */
export type ChannelKind = 'ntfy' | 'webhook' | 'discord'

/**
 * Events a notification channel can receive. Additive: channels with
 * events: null pick up new members of this union automatically.
 */
export type NotificationEvent = 'target.hit' | 'listing.new'

/** A user's notification destination — the /api/me/channels routes. */
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

/** POST /api/me/tokens body. */
export interface ApiTokenCreateRequest {
  /** 1–64 chars; 422 validation_error with fields.name otherwise */
  name: string
  /** non-empty subset of the known scopes; 422 with fields.scopes otherwise */
  scopes: ApiTokenScope[]
  /** omit/null = never expires; 422 with fields.expires_in_days below 1 */
  expires_in_days?: number | null
}

/** One row of GET /api/admin/users; `item_count` is the user's watch count. */
export interface AdminUser {
  id: number
  email: string
  role: UserRole
  is_active: boolean
  created_at: string
  item_count: number
}

/** PATCH /api/admin/users/{id} body; omitted fields are left unchanged. */
export interface AdminUserUpdateRequest {
  is_active?: boolean
  role?: UserRole
}

/** A pending invite — GET/POST /api/admin/invites. A null `email` lets anyone accept it. */
export interface Invite {
  id: number
  token: string
  email: string | null
  expires_at: string
  created_at: string
}

/** POST /api/admin/invites body; no email makes an invite anyone can accept. */
export interface InviteCreateRequest {
  email?: string
}
