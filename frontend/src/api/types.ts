/**
 * TypeScript mirror of the Snagr API contract.
 * This file IS the contract — docs/BACKEND_REQUIREMENTS.md is written from it.
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
    /** present on 409 run_in_progress */
    run_id?: number
  }
}

// ---------------------------------------------------------------------------
// Instance / auth

export interface InstanceInfo {
  version: string
  /** null when the admin hasn't configured NTFY_SERVER_URL */
  ntfy_server_url: string | null
  /** true only while the instance has zero users (first-admin bootstrap) */
  registration_open: boolean
}

export type UserRole = 'admin' | 'user'

export interface User {
  id: number
  email: string
  role: UserRole
  ntfy_topic: string | null
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
  created_at: string
}

export interface SiteCreateRequest {
  name: string
  base_url: string
}

export interface SiteUpdateRequest {
  name?: string
  base_url?: string
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
  last_checked_at: string | null
  created_at: string
  discovered_by_run_id: number | null
}

export interface ItemDetail extends ItemSummary {
  listings: Listing[]
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
  checked_at: string
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
// Agent runs

export type RunScope = 'global' | 'category' | 'site' | 'item'
export type RunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface RunStats {
  listings_checked: number
  prices_found: number
  new_listings: number
  errors: number
}

export interface AgentRun {
  id: number
  scope: RunScope
  scope_id: number | null
  /** human label: "Everything", "Category: GPUs", "Site: newegg.com", "Item: RTX 4070" */
  scope_label: string
  status: RunStatus
  started_at: string | null
  finished_at: string | null
  stats: RunStats | null
  error: string | null
  created_at: string
  /** highest event seq written so far */
  last_seq: number
}

export interface RunCreateRequest {
  scope: RunScope
  scope_id?: number
}

export type RunEventLevel = 'info' | 'success' | 'warn' | 'error'

export type RunEventType =
  | 'run_started'
  | 'site_started'
  | 'item_started'
  | 'listing_check'
  | 'price_found'
  /** candidate scored against the item's criteria — payload: url, title, match_score, match_summary, tracked */
  | 'listing_evaluated'
  | 'listing_discovered'
  /** tracked listing sold/ended; slot freed — payload: listing_id, item_id */
  | 'listing_ended'
  | 'error'
  | 'run_finished'

export interface RunEvent {
  run_id: number
  seq: number
  ts: string
  level: RunEventLevel
  event_type: RunEventType
  message: string
  payload: Record<string, unknown> | null
}

export interface RunListParams {
  status?: RunStatus
  scope?: RunScope
  page?: number
  per_page?: number
}

// ---------------------------------------------------------------------------
// SSE stream (GET /api/events)
//
// Named events on the stream:
//   run.snapshot  → RunSnapshotData   (sent once on every connect/reconnect)
//   run.started   → { run: AgentRun }
//   run.event     → RunEvent
//   run.finished  → { run: AgentRun }  (stats populated)
//   run.failed    → { run: AgentRun }  (error populated)
// Heartbeat: comment line `: ping` every 15s.
// Reconnect contract: compare snapshot last_seq with the highest rendered seq
// and backfill gaps via GET /api/runs/{id}/events?after_seq=N.

export interface RunSnapshotData {
  active_runs: Pick<AgentRun, 'id' | 'status' | 'scope' | 'scope_label' | 'last_seq'>[]
}

// ---------------------------------------------------------------------------
// Settings / admin

export interface MeUpdateRequest {
  email?: string
  ntfy_topic?: string | null
}

export interface PasswordChangeRequest {
  current_password: string
  new_password: string
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
